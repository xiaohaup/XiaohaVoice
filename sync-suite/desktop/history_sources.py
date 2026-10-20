"""Read native history and committed local imports without rewriting native history."""
from functools import lru_cache
from pathlib import Path
import json

MAX_BYTES = 50_000_000


def import_path(history_path):
    return Path(history_path).parent/'imports/shandianshuo/records.json' if history_path else None


def revision(history_path):
    paths = [Path(history_path), import_path(history_path)] if history_path else []
    result = []
    for path in paths:
        try:
            s = path.stat()
            result.append((str(path), s.st_mtime_ns, s.st_size))
        except FileNotFoundError:
            result.append((str(path), None, None))
    return tuple(result)


def _read(path):
    if not path.exists(): return None
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('本机历史较大，暂不载入；原文件没有改变')
    return json.loads(path.read_text(encoding='utf-8'))


@lru_cache(maxsize=4)
def _sources(stamp):
    if not stamp: return (), None
    native = _read(Path(stamp[0][0]))
    if native is not None and not isinstance(native, list):
        raise ValueError('本机历史格式无法读取；原文件没有改变')
    ledger = _read(Path(stamp[1][0]))
    if ledger is not None:
        if (not isinstance(ledger, dict) or ledger.get('schema_version') != 1
                or ledger.get('source') != 'shandianshuo' or not isinstance(ledger.get('records'), list)
                or not isinstance(ledger.get('summary'), dict)):
            raise ValueError('迁入历史格式无法读取；原文件没有改变')
    return tuple(native or [])+tuple(ledger['records'] if ledger else []), ledger


def read_sources(history_path):
    return _sources(revision(history_path))[0]


def migration_status(history_path):
    ledger = _sources(revision(history_path))[1]
    return ({'available': True, **ledger['summary'], 'imported_at': ledger['imported_at']}
            if ledger else {'available': False})


def source_characters(row, fallback):
    value = row.get('source_characters')
    if (row.get('source') == 'shandianshuo' and type(value) is int
            and 0 <= value <= len(row.get('text', ''))):
        return value
    return fallback


def archive_path(history_path):
    ledger = _sources(revision(history_path))[1]
    if not ledger: return None
    digest = ledger.get('archive_sha256', '')
    if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('原始归档校验信息无效')
    path = import_path(history_path).parent/'archives'/(digest+'.json')
    if not path.is_file(): raise ValueError('原始归档暂不可用，迁入历史仍保留')
    return path
