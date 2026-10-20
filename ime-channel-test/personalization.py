"""Explicit single-pass local corrections. No network or transcript persistence."""
import json
from pathlib import Path
import re


class Personalizer:
    def __init__(self, path, local_path=None):
        self.pattern = None
        self.replacements = {}
        try:
            def load(p):
                p = Path(p)
                if not p.exists(): return {}
                if p.stat().st_size > 5_000_000: raise ValueError('dictionary too large')
                return json.loads(p.read_text(encoding='utf-8'))
            cloud = load(path)
            local = load(local_path) if local_path else {}
            if local_path and local:
                if local.get('enabled') is not True: return
                words = (cloud.get('words', []) if cloud.get('enabled') is True else []) + local.get('words', [])
            else:
                if cloud.get('enabled') is not True: return
                words = cloud.get('words', [])
            entries, targets = [], {}
            for word in words:
                if not isinstance(word, dict) or word.get('enabled', True) is not True: continue
                term = word.get('term')
                if not isinstance(term, str) or not term or len(term) > 100: continue
                for alias in word.get('aliases', []):
                    if not isinstance(alias, str) or not alias or len(alias) > 100 or alias == term: continue
                    sensitive = word.get('case_sensitive', True) is not False
                    targets.setdefault(alias.casefold(), set()).add(term)
                    entries.append((alias, term, sensitive))
            buckets = {'word_sensitive':[], 'word_fold':[], 'other_sensitive':[], 'other_fold':[]}
            for alias, term, sensitive in sorted(set(entries), key=lambda x: (-len(x[0]), x)):
                if len(targets[alias.casefold()]) > 1: continue
                kind = 'word' if alias.isascii() and alias.replace('_', '').isalnum() else 'other'
                buckets[kind + ('_sensitive' if sensitive else '_fold')].append(re.escape(alias))
                self.replacements[alias.casefold()] = term
            def union(kind):
                parts = []
                if buckets[kind+'_sensitive']: parts.append('(?:'+'|'.join(buckets[kind+'_sensitive'])+')')
                if buckets[kind+'_fold']: parts.append('(?i:'+'|'.join(buckets[kind+'_fold'])+')')
                return '|'.join(parts)
            other, words = union('other'), union('word')
            pieces = ([other] if other else []) + ([r'(?<![A-Za-z0-9_])(?:'+words+r')(?![A-Za-z0-9_])'] if words else [])
            if pieces: self.pattern = re.compile('|'.join(pieces))
        except (OSError, ValueError, TypeError, AttributeError):
            self.replacements = {}; self.pattern = None

    def apply(self, text):
        if not self.pattern: return text
        return self.pattern.sub(lambda m: self.replacements[m.group(0).casefold()], text)
