"""Explicit, local-only Shandianshuo import. Preview by default, atomic commit with --apply."""
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL
import argparse
import hashlib
import json
import math
import os
import re
import tempfile

from desktop.history_sources import import_path, MAX_BYTES

WORD = re.compile(r'[\u4e00-\u9fff]|[a-zA-Z]+')


def private_write(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temp = tempfile.mkstemp(prefix='.import-', dir=path.parent)
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'wb') as f:
            f.write(data); f.flush(); os.fsync(f.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp): os.unlink(temp)


def encode(value):
    return (json.dumps(value, ensure_ascii=False, separators=(',', ':'), sort_keys=True)+'\n').encode()


def convert(source):
    if source.stat().st_size > MAX_BYTES: raise ValueError('源历史文件过大，未导入')
    data = source.read_bytes()
    value = json.loads(data)
    if not isinstance(value, dict) or str(value.get('version')) != '1.0' or not isinstance(value.get('records'), list):
        raise ValueError('不支持这份闪电说历史格式，未导入')
    seen, records, counts, types = set(), [], Counter(), Counter()
    for row in value['records']:
        if not isinstance(row, dict): raise ValueError('源记录格式无效，未导入')
        rid, status, kind = row.get('id'), row.get('status'), row.get('record_type')
        if not isinstance(rid, str) or not rid or rid in seen:
            raise ValueError('源编号缺失或重复，未导入')
        seen.add(rid)
        if status not in ('success', 'empty', 'error') or kind not in ('voice_input', 'voice_assistant'):
            raise ValueError('发现未知记录状态或类型，未导入')
        counts[status] += 1
        if status != 'success': continue
        text, duration, stamp = row.get('text'), row.get('duration_ms'), row.get('timestamp')
        if (not isinstance(text, str) or not text.strip() or type(duration) not in (int, float)
                or not math.isfinite(duration) or duration < 0 or type(stamp) not in (int, float)
                or not math.isfinite(stamp) or stamp <= 0):
            raise ValueError('成功记录的文字、时长或时间无效，未导入')
        date = datetime.fromtimestamp(stamp, timezone.utc)
        if date > datetime.now(timezone.utc): raise ValueError('源记录存在未来时间，未导入')
        app = (row.get('focus_info') or {}).get('app_name')
        record = {'id': str(uuid5(NAMESPACE_URL, 'xiaoha-voice:shandianshuo:'+rid)),
                  'created_at': date.isoformat(), 'text': text, 'seconds': duration/1000,
                  'application': app if isinstance(app, str) and app else None,
                  'source': 'shandianshuo', 'source_id': rid, 'record_type': kind,
                  'source_characters': len(WORD.findall(text))}
        if isinstance(row.get('original_text'), str): record['original_text'] = row['original_text']
        if isinstance(row.get('ai_corrected_text'), str): record['ai_corrected_text'] = row['ai_corrected_text']
        records.append(record); types[kind] += 1
    summary = {'source_records': len(value['records']), 'completed_records': len(records),
               'empty_records': counts['empty'], 'error_records': counts['error'],
               'voice_input_records': types['voice_input'], 'voice_assistant_records': types['voice_assistant'],
               'characters': sum(r['source_characters'] for r in records),
               'seconds': round(sum(r['seconds'] for r in records), 3),
               'first_at': min((r['created_at'] for r in records), default=None),
               'last_at': max((r['created_at'] for r in records), default=None),
               'character_method': 'shandianshuo: Han characters + Latin words; digits excluded'}
    for kind in ('voice_input', 'voice_assistant'):
        subset = [r for r in records if r['record_type'] == kind]
        summary[kind+'_characters'] = sum(r['source_characters'] for r in subset)
        summary[kind+'_seconds'] = round(sum(r['seconds'] for r in subset), 3)
    return data, records, summary


def run(source, history, apply=False):
    source, history = Path(source).resolve(), Path(history).resolve()
    if not history.is_file(): raise ValueError('请指定已有的小哈语音本机历史')
    data, records, summary = convert(source)
    ledger_path = import_path(history)
    if source == history or source == ledger_path: raise ValueError('源文件与目标冲突')
    old = json.loads(ledger_path.read_text()) if ledger_path.exists() else None
    if old and (old.get('source') != 'shandianshuo' or old.get('schema_version') != 1):
        raise ValueError('已有迁入文件格式不同，未覆盖')
    existing = {r['id']: r for r in old['records']} if old else {}
    added = sum(r['id'] not in existing for r in records)
    updated = sum(r['id'] in existing and r != existing[r['id']] for r in records)
    merged_rows = {**existing, **{r['id']:r for r in records}}
    retained = len(merged_rows)-len(records)
    if retained:
        summary['retained_from_previous_import'] = retained
        summary['completed_records'] = len(merged_rows)
        summary['characters'] = sum(r['source_characters'] for r in merged_rows.values())
        summary['seconds'] = round(sum(r['seconds'] for r in merged_rows.values()),3)
        summary['first_at'] = min(r['created_at'] for r in merged_rows.values())
        summary['last_at'] = max(r['created_at'] for r in merged_rows.values())
        for kind in ('voice_input','voice_assistant'):
            subset = [r for r in merged_rows.values() if r['record_type']==kind]
            summary[kind+'_records'] = len(subset)
            summary[kind+'_characters'] = sum(r['source_characters'] for r in subset)
            summary[kind+'_seconds'] = round(sum(r['seconds'] for r in subset),3)
    digest = hashlib.sha256(data).hexdigest()
    result = {'applied': apply, 'added': added, 'updated': updated, 'archive_sha256': digest, **summary}
    if not apply: return result
    directory = ledger_path.parent
    for path in (history.parent/'imports', directory, directory/'archives'):
        path.mkdir(exist_ok=True, mode=0o700); path.chmod(0o700)
    archive = directory/'archives'/(digest+'.json')
    if archive.exists():
        if hashlib.sha256(archive.read_bytes()).hexdigest() != digest: raise ValueError('原始归档校验失败，未提交')
    else: private_write(archive, data)
    if old and old.get('archive_sha256') == digest and added == 0 and updated == 0:
        result['unchanged'] = True
        return result
    for row in records: existing[row['id']] = row
    # Retain earlier imported rows if the source app later trims its history.
    merged = sorted(existing.values(), key=lambda r: r['created_at'], reverse=True)
    if old:
        backup = directory/'backups'/('records-'+hashlib.sha256(encode(old)).hexdigest()+'.json')
        private_write(backup, encode(old)); backup.parent.chmod(0o700)
    ledger = {'schema_version': 1, 'source': 'shandianshuo', 'imported_at': datetime.now(timezone.utc).isoformat(),
              'archive_sha256': digest, 'summary': summary, 'records': merged}
    private_write(ledger_path, encode(ledger))
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--history', required=True, type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(run(args.source, args.history, args.apply), ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
