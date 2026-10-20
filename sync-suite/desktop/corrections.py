"""Device-local correction editor, separate from the synced account wordbook."""
from desktop.client import read_json, write_json
import threading
from uuid import uuid4

DEFAULT = {'enabled': True, 'words': [
    {'term': 'Claude', 'aliases': ['Cloud'], 'enabled': True, 'case_sensitive': False}
]}


def validate(value):
    if not isinstance(value, dict) or type(value.get('enabled')) is not bool or not isinstance(value.get('words'), list) or len(value['words']) > 500:
        raise ValueError('最多保存500条纠正规则')
    words, targets = [], {}
    for row in value['words']:
        if not isinstance(row, dict): raise ValueError('规则格式不正确')
        term, aliases = row.get('term'), row.get('aliases')
        if not isinstance(term, str) or not term.strip() or len(term) > 100 or not isinstance(aliases, list) or len(aliases) > 20:
            raise ValueError('正确词和误识别词均需填写，单个词不超过100字')
        aliases = list(dict.fromkeys(a.strip() for a in aliases if isinstance(a, str) and a.strip()))
        if not aliases or any(len(a) > 100 for a in aliases): raise ValueError('请填写至少一个有效的误识别词')
        enabled, case = row.get('enabled', True), row.get('case_sensitive', False)
        if type(enabled) is not bool or type(case) is not bool: raise ValueError('规则开关无效')
        if enabled:
            for alias in aliases:
                key = alias.casefold()
                if key in targets and targets[key] != term.strip(): raise ValueError('同一个误识别词不能指向两个正确词')
                targets[key] = term.strip()
        words.append({'term': term.strip(), 'aliases': aliases, 'enabled': enabled, 'case_sensitive': case})
    return {'enabled': value['enabled'], 'words': words}


class Corrections:
    def __init__(self, path):
        self.path = path
        self.draft_path = path.with_name('corrections-draft.json')
        self.lock = threading.RLock()
    def load(self): return read_json(self.path, DEFAULT)
    def save(self, value):
        with self.lock:
            clean = validate(value)
            write_json(self.path, clean)
            write_json(self.draft_path, {'revision': str(uuid4()), 'value': clean})
    def draft(self):
        with self.lock:
            return read_json(self.draft_path, {'revision': None, 'value': self.load()})
    def save_draft(self, value, revision):
        with self.lock:
            if revision != self.draft()['revision']:
                raise DraftConflict('另一个窗口已更新词库；你的输入仍保留在当前窗口和本机草稿，请先核对两个版本')
            if not isinstance(value, dict) or type(value.get('enabled')) is not bool or not isinstance(value.get('words'), list) or len(value['words']) > 500:
                raise ValueError('最多保存500条纠正规则')
            words = []
            for row in value['words']:
                if not isinstance(row, dict) or not isinstance(row.get('term'), str) or len(row['term']) > 100 or not isinstance(row.get('aliases'), list) or len(row['aliases']) > 20:
                    raise ValueError('词条格式无效')
                if any(not isinstance(a, str) or len(a)>100 for a in row['aliases']) or any(type(row.get(k, default)) is not bool for k,default in [('enabled',True),('case_sensitive',False)]):
                    raise ValueError('词条格式无效')
                words.append({'term':row['term'], 'aliases':row['aliases'], 'enabled':row.get('enabled',True), 'case_sensitive':row.get('case_sensitive',False)})
            clean={'enabled':value['enabled'], 'words':words}
            result={'revision':str(uuid4()), 'value':clean}
            # A partial or conflicting row is still a saved draft. Recognition
            # continues using the last valid set until a valid set is available.
            write_json(self.draft_path, result)
            complete=[w for w in words if w['term'].strip() and any(a.strip() for a in w['aliases'])]
            result.update(draft_saved=True, incomplete=len(words)-len(complete), applied=False)
            try:
                compiled=validate({'enabled':clean['enabled'],'words':complete})
                write_json(self.path, compiled)
                result['applied']=True
            except ValueError as exc: result['detail']=str(exc)
            return result

class DraftConflict(ValueError): pass
