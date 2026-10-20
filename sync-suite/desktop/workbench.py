"""Local workbench: reads this device's history, never sends it to a sync server."""
from __future__ import annotations
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
import json
import asyncio
import math
import time
from pathlib import Path
import secrets
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse

from desktop.client import characters, read_json, write_json
from desktop.history_sources import read_sources, revision, migration_status, source_characters, archive_path

try:
    ZONE = ZoneInfo('Asia/Shanghai')
except ZoneInfoNotFoundError:  # Windows may not ship an IANA database; this workbench uses Beijing time.
    ZONE = timezone(timedelta(hours=8), name='Asia/Shanghai')


class LocalWorkbench:
    def __init__(self, directory, history_path, now=None):
        self.directory = Path(directory)
        self.history_path = Path(history_path) if history_path else None
        self.now = now or (lambda: datetime.now(ZONE))
        self.session = secrets.token_urlsafe(32)
        self.csrf = secrets.token_urlsafe(32)
        self.path = self.directory / 'workbench.json'
        from desktop.corrections import Corrections
        self.corrections = Corrections(self.history_path.parent/'corrections.json' if self.history_path else self.directory/'corrections.json')
        self._summary_cache = {}

    def preferences(self):
        value = read_json(self.path, {})
        return {'theme': value.get('theme', 'cocoa'), 'text_size': value.get('text_size', 'normal'),
                'typing_speed': value.get('typing_speed', 40)}

    def save_preferences(self, value):
        if (set(value) != {'theme', 'text_size', 'typing_speed'}
                or value['theme'] not in ('mint', 'ink', 'cocoa')
                or value['text_size'] not in ('normal', 'large')
                or type(value['typing_speed']) is not int or not 10 <= value['typing_speed'] <= 200):
            raise ValueError('请检查配色、字号和打字速度（10—200字/分钟）')
        write_json(self.path, value)

    def records(self, query='', period='all', day=''):
        selected_day = None
        if day:
            try:
                selected_day = date.fromisoformat(day)
                if selected_day.isoformat() != day: raise ValueError()
            except (TypeError, ValueError):
                raise ValueError('请选择有效日期')
        today = self.now().astimezone(ZONE).date()
        cutoff = {'today': today, '7': today-timedelta(days=6), '30': today-timedelta(days=29),
                  'month': today.replace(day=1), 'all': None}.get(period)
        if period not in ('today', '7', '30', 'month', 'all'):
            raise ValueError('时间范围无效')
        cache_key = (self.revision(), today.isoformat())
        if getattr(self, '_record_cache_key', None) != cache_key:
            seen, result = set(), []
            for row in read_sources(self.history_path):
                try:
                    rid, text = str(row['id']), row['text']
                    if rid in seen or not isinstance(text, str) or not text.strip(): continue
                    created = row.get('created_at', row.get('createdAt'))
                    if isinstance(created, (int, float)):
                        stamp = datetime.fromtimestamp(978307200 + created, timezone.utc)
                    else:
                        stamp = datetime.fromisoformat(created.replace('Z', '+00:00'))
                        if stamp.tzinfo is None: stamp = stamp.replace(tzinfo=ZONE)
                    stamp = stamp.astimezone(ZONE)
                    seconds = float(row['seconds'])
                    if not math.isfinite(seconds) or seconds < 0 or stamp.date() > today: continue
                    seen.add(rid)
                    chars = source_characters(row, None)
                    result.append({'id': rid, 'created_at': stamp.isoformat(), 'text': text,
                                   'seconds': seconds, 'characters': characters(text) if chars is None else chars,
                                   'application': row.get('application') if isinstance(row.get('application'), str) else None,
                                   'source': row.get('source'), 'record_type': row.get('record_type'),
                                   **({'original_text':row['original_text']} if isinstance(row.get('original_text'),str) else {})})
                except (KeyError, TypeError, ValueError, OverflowError): continue
            self._record_cache = sorted(result, key=lambda r: r['created_at'], reverse=True)
            self._record_cache_key = cache_key
        return [r for r in self._record_cache
                if (not selected_day or r['created_at'][:10] == selected_day.isoformat())
                and (not cutoff or r['created_at'][:10] >= cutoff.isoformat())
                and query.casefold() in r['text'].casefold()]

    def revision(self):
        return str(revision(self.history_path))

    def summary(self, period):
        key = (self.revision(), json.dumps(self.corrections.load(),sort_keys=True), period, self.now().astimezone(ZONE).date().isoformat(), self.preferences()['typing_speed'])
        if key in self._summary_cache: return self._summary_cache[key]
        rows = self.records(period=period)
        count = sum(r['characters'] for r in rows)
        seconds = sum(r['seconds'] for r in rows)
        grouped = defaultdict(lambda: {'characters': 0, 'sessions': 0})
        for r in rows:
            day = r['created_at'][:10]
            grouped[day]['characters'] += r['characters']
            grouped[day]['sessions'] += 1
        today = self.now().astimezone(ZONE).date()
        year_start=(today-timedelta(days=364)).isoformat()
        all_days = sorted({r['created_at'][:10] for r in self.records() if r['created_at'][:10]>=year_start})
        longest = current = 0
        previous = None
        for day in all_days:
            date = datetime.fromisoformat(day).date()
            current = current + 1 if previous and date == previous + timedelta(days=1) else 1
            longest = max(longest, current)
            previous = date
        speed = self.preferences()['typing_speed']
        days = [(today-timedelta(days=i)).isoformat() for i in range(364, -1, -1)]
        # Activity always shows a complete year, independently of the range selector.
        activity = defaultdict(lambda: {'characters': 0, 'sessions': 0})
        for r in self.records():
            activity[r['created_at'][:10]]['characters'] += r['characters']
            activity[r['created_at'][:10]]['sessions'] += 1
        from desktop.analytics import word_counts, app_counts
        vocabulary = [w.get('term') for w in self.corrections.load().get('words', []) if isinstance(w,dict)]
        words, word_total = word_counts(rows, vocabulary)
        apps, app_total = app_counts(rows)
        result = {'average_seconds': round(seconds/len(rows), 1) if rows else 0,
                'average_characters': round(count/len(rows), 1) if rows else 0,
                'applications': apps, 'application_details':app_counts(rows,limit=None)[0], 'application_sessions': app_total, 'unknown_application_sessions': len(rows)-app_total,
                'words': words, 'word_occurrences': word_total,
                'characters': count, 'sessions': len(rows), 'seconds': seconds,
                'migration': migration_status(self.history_path),
                'words_per_minute': round(count*60/seconds) if seconds else 0,
                'estimated_saved_minutes': round(max(0, count/speed-seconds/60), 1),
                'typing_speed': speed, 'active_days': len(all_days), 'longest_streak': longest,
                'days': [{'date': day, **activity[day]} for day in days],
                'per_day': [{'date': day, **grouped[day]} for day in sorted(grouped)]}
        self._summary_cache = {key: result}
        return result


def install_workbench(app, companion, origin, root):
    from hmac import compare_digest
    store = LocalWorkbench(companion.directory, companion.history_path)
    app.state.workbench = store

    @app.middleware('http')
    async def protect_workbench(request, call_next):
        path = request.url.path
        if path.startswith('/workbench'):
            if request.headers.get('sec-fetch-site') == 'cross-site':
                return JSONResponse({'detail': '仅允许本机页面访问'}, 403)
            if path.startswith('/workbench/api/'):
                if not compare_digest(request.cookies.get('xh_workbench', ''), store.session):
                    return JSONResponse({'detail': '请从小哈语音重新打开工作台'}, 401)
                if request.method != 'GET':
                    if (request.headers.get('origin') != origin
                            or not compare_digest(request.headers.get('x-csrf-token', ''), store.csrf)
                            or 'application/json' not in request.headers.get('content-type', '')):
                        return JSONResponse({'detail': '请求来源不匹配，请重新打开工作台'}, 403)
                    data = await request.body()
                    if len(data) > (2_000_000 if path in ('/workbench/api/corrections','/workbench/api/corrections-draft') else 65536):
                        return JSONResponse({'detail': '内容过大'}, 413)
            try:
                response = await call_next(request)
            except (ValueError, OSError):
                return JSONResponse({'detail': '本机数据暂时无法读取或保存，原历史文件没有改变'}, 422)
            response.headers['Cache-Control'] = 'no-store'
            response.headers['Content-Security-Policy'] = "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
            response.headers['X-Content-Type-Options'] = 'nosniff'
            return response
        return await call_next(request)

    @app.get('/workbench')
    def workbench():
        response = FileResponse(root/'web/workbench.html')
        response.set_cookie('xh_workbench', store.session, httponly=True, samesite='strict', path='/workbench')
        return response

    @app.get('/workbench/api/status')
    def status():
        return {'csrf': store.csrf, 'preferences': store.preferences(),
                'cloud_configured': bool(companion.config['server']), 'version': '0.3.7',
                'history_available': bool(store.history_path and store.history_path.is_file())}

    @app.get('/workbench/api/history')
    def history(q: str = '', period: str = 'all', day: str = ''):
        if len(q) > 200:
            return JSONResponse({'detail': '搜索文字过长'}, 422)
        return {'records': store.records(q, period, day), 'migration':migration_status(store.history_path)}

    @app.get('/workbench/api/summary')
    def summary(period: str = 'all'):
        return store.summary(period)

    @app.get('/workbench/api/imports/shandianshuo/archive')
    def imported_archive():
        path = archive_path(store.history_path)
        if path is None: return JSONResponse({'detail':'尚未迁入闪电说记录'}, 404)
        return FileResponse(path, media_type='application/json', filename='闪电说原始记录.json')

    @app.post('/workbench/api/preferences')
    async def preferences(request: Request):
        store.save_preferences(await request.json())
        return {'ok': True}

    @app.get('/workbench/api/events')
    async def events(request: Request):
        async def stream():
            previous = None
            while not await request.is_disconnected():
                current = store.revision()
                if current != previous:
                    yield 'event: history\ndata: ' + json.dumps({'revision': current}) + '\n\n'
                    previous = current
                else:
                    yield ': keepalive\n\n'
                await asyncio.sleep(0.25)
        return StreamingResponse(stream(), media_type='text/event-stream', headers={'X-Accel-Buffering':'no'})

    @app.get('/workbench/api/corrections')
    def corrections_get(): return store.corrections.load()

    @app.post('/workbench/api/corrections')
    async def corrections_post(request: Request):
        store.corrections.save(await request.json())
        return {'ok': True, 'value': store.corrections.load()}

    @app.get('/workbench/api/corrections-draft')
    def corrections_draft_get(): return store.corrections.draft()

    @app.post('/workbench/api/corrections-draft')
    async def corrections_draft_post(request: Request):
        from desktop.corrections import DraftConflict
        body=await request.json()
        try: return store.corrections.save_draft(body.get('value'),body.get('revision'))
        except DraftConflict as exc: return JSONResponse({'detail':str(exc)},409)

    from desktop.asr_settings import ASRSettings
    from desktop.runtime_settings import RuntimeSettings
    from desktop.runtime_log import append as diagnostic, recent
    data_dir=store.history_path.parent if store.history_path else store.directory
    runtime=RuntimeSettings(data_dir)
    @app.get('/workbench/api/runtime')
    def runtime_get(): return runtime.load()
    @app.post('/workbench/api/runtime')
    async def runtime_post(request: Request):
        value=runtime.save(await request.json());diagnostic(data_dir,'settings',phase='saved');return value
    @app.get('/workbench/api/logs')
    def logs_get(): return {'records':recent(data_dir)}
    @app.post('/workbench/api/network-check')
    def network_check():
        import httpx,time
        begin=time.perf_counter()
        try:
            with httpx.Client(timeout=8,follow_redirects=False,**runtime.httpx_options()) as client:
                response=client.head('https://frontier-audio-ime-ws.doubao.com/')
            diagnostic(data_dir,'network',phase='connected',status=response.status_code)
            return {'connected':True,'status':response.status_code,'milliseconds':round((time.perf_counter()-begin)*1000)}
        except Exception as exc:
            diagnostic(data_dir,'network',phase='error',error_kind=type(exc).__name__)
            return {'connected':False,'detail':'连接未完成，请检查代理地址、代理软件和网络。没有上传录音。'}
    @app.get('/workbench/api/ime-readiness')
    def ime_readiness():
        import os
        identity=Path(os.environ.get('XH_VOICE_IDENTITY') or root.parent/'ime-channel-test/private')
        device=read_json(identity/'device.json',{})
        return {'ready':str(device.get('device_id','0')) not in ('','0'),'attempted':(identity/'registration-attempt.json').exists()}
    @app.post('/workbench/api/ime-initialize')
    async def ime_initialize(request: Request):
        body=await request.json()
        if body.get('confirmed') is not True:return JSONResponse({'detail':'需先确认首次设备初始化'},422)
        import os,sys
        engine=Path(os.environ.get('XH_VOICE_ENGINE') or root.parent/'ime-channel-test')
        if str(engine) not in sys.path:sys.path.insert(0,str(engine))
        from channel_probe import credentials,constants
        try:
            await asyncio.to_thread(credentials,constants(),True)
            diagnostic(data_dir,'initialize',phase='done');return {'ready':True}
        except Exception:
            diagnostic(data_dir,'initialize',phase='error')
            return JSONResponse({'detail':'首次初始化未完成，已保留本机状态。不会反复注册，请检查网络或选择正式API。'},422)
    asr = ASRSettings(store.history_path.parent/'asr-settings.json' if store.history_path else store.directory/'asr-settings.json')
    @app.get('/workbench/api/asr')
    def asr_get(): return asr.public()
    @app.post('/workbench/api/asr')
    async def asr_post(request: Request):
        try:return {'ok': True, 'value': await asyncio.to_thread(asr.save,await request.json())}
        except ValueError as exc:return JSONResponse({'detail':str(exc)},422)

    test_lock=asyncio.Lock()
    credential_task=None
    async def saved_credential():
        nonlocal credential_task
        if credential_task is None:
            credential_task=asyncio.create_task(asyncio.to_thread(asr.test_config))
        try:return await asyncio.wait_for(asyncio.shield(credential_task),20)
        finally:
            if credential_task is not None and credential_task.done():credential_task=None

    @app.post('/workbench/api/asr-credential')
    async def asr_credential(request: Request):
        body=await request.json()
        if body.get('reveal') is not True:
            return JSONResponse({'detail':'仅在点击显示凭证时读取'},422)
        if body.get('revision')!=asr.config().get('revision'):
            return JSONResponse({'detail':'设置已更新，请重新载入后查看'},409)
        try:config,credential=await saved_credential()
        except asyncio.TimeoutError:
            return JSONResponse({'detail':'正在等待系统钥匙串授权，请完成后再点眼睛。'},408)
        except ValueError as exc:return JSONResponse({'detail':str(exc)},422)
        if config.get('revision')!=body.get('revision') or asr.config().get('revision')!=body.get('revision'):
            return JSONResponse({'detail':'设置已更新，请重新载入后查看'},409)
        return JSONResponse({'credential':credential},headers={'Cache-Control':'no-store'})

    @app.post('/workbench/api/asr-test')
    @app.post('/workbench/api/asr-speed-test')
    async def asr_test(request: Request):
        started=time.perf_counter()
        if test_lock.locked():return JSONResponse({'detail':'正在测试，请稍候'},409)
        body=await request.json()
        speed=request.url.path.endswith('speed-test')
        if speed and body.get('confirmed') is not True:
            return JSONResponse({'detail':'请手动点击识别测速；内置测试音频会发送到所选通道'},422)
        if body.get('revision')!=asr.config().get('revision'):
            return JSONResponse({'detail':'设置已更新，请先重新载入保存的配置再测试'},409)
        async with test_lock:
            config=asr.config();provider=body.get('provider',config['provider']);credential=None
            if provider not in ('ime','volcengine'):
                return JSONResponse({'detail':'测试通道无效'},422)
            try:
                if provider=='volcengine':config,credential=await saved_credential()
            except asyncio.TimeoutError:
                return JSONResponse({'detail':'正在等待系统钥匙串授权。请完成系统验证后再点测试；其他功能可正常使用。'},408)
            except ValueError as exc:return JSONResponse({'detail':str(exc)},422)
            if body.get('revision')!=config.get('revision'):
                return JSONResponse({'detail':'设置已更新，请先重新载入保存的配置再测试'},409)
            import os,sys
            engine=Path(os.environ.get('XH_VOICE_ENGINE') or root.parent/'ime-channel-test')
            if str(engine) not in sys.path:sys.path.insert(0,str(engine))
            config['proxy']=runtime.websocket_proxy()
            try:
                if speed:
                    pcm=(root/'desktop/assets/api-check.pcm').read_bytes()
                    if provider=='ime':
                        from channel_probe import benchmark as ime_benchmark
                        result=await asyncio.wait_for(ime_benchmark(pcm),30)
                    else:
                        from volcengine_asr import benchmark
                        result=await asyncio.wait_for(benchmark(config,credential,pcm),25)
                else:
                    if provider=='ime':
                        from channel_probe import probe as ime_probe
                        result=await asyncio.wait_for(ime_probe(),12)
                    else:
                        from volcengine_asr import probe
                        result=await asyncio.wait_for(probe(config,credential),12)
            except Exception as exc:
                # Do not return raw server messages/headers; they may contain credentials.
                from websockets.exceptions import InvalidStatus
                if provider=='ime':
                    detail='输入法通道测试未完成，请检查这台设备是否已初始化以及网络是否正常。未重新注册身份，也未切换火山API。'
                elif isinstance(exc,InvalidStatus):
                    code=exc.response.status_code
                    detail={401:'认证失败，请检查语音控制台的 API Key 或 Access Token。',403:'服务拒绝访问，请检查流式识别2.0的开通状态、资源类型与额度。'}.get(code,'服务返回 HTTP '+str(code)+'，请稍后重试。')
                elif isinstance(exc,(TimeoutError,asyncio.TimeoutError)):detail='测试超时，请检查网络和代理。设置已保留。'
                else:detail='服务未接受本次测试，请检查凭证、流式识别2.0资源和网络。'
                result={'ok':False,'detail':detail}
                diagnostic(data_dir,'asr_test',phase='error',error_kind=type(exc).__name__)
            else:diagnostic(data_dir,'asr_test',phase='connected')
            result['total_ms']=round((time.perf_counter()-started)*1000)
            current=await asyncio.to_thread(asr.record_test,config.get('revision'),result,'speed_test' if speed else 'connection_test',provider)
            return {**result,'current':current,'provider':provider}

    @app.get('/workbench/preview')
    def preview():
        response = FileResponse(root/'web/workbench-next.html')
        response.set_cookie('xh_workbench', store.session, httponly=True, samesite='strict', path='/workbench')
        return response
