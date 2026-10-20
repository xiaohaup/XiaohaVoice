"""Local-only application and word frequencies; no transcript cache on disk."""
from collections import Counter
from functools import lru_cache
import logging
import re
import threading

STOP = set('这个 那个 然后 就是 可以 需要 一个 我们 你们 他们 时候 还有 因为 所以 但是 这样 那样 已经 进行 一下 什么 自己 没有 现在 不是 如果 知道 怎么 是否 还是 这些 觉得 非常 的了是在我你他她它也都和与及有就而把被给着过呢吗啊吧呀嗯哦'.split())
_tokenizer = None
_vocabulary = None
_tokenizer_lock = threading.RLock()

@lru_cache(maxsize=40000)
def _tokens(text):
    result = []
    for token in _tokenizer.cut(text, HMM=False):
        token = token.strip()
        if len(token) < 2 or token in STOP or not re.fullmatch(r'[\w\u4e00-\u9fff+-]+', token) or token.isnumeric(): continue
        result.append(token)
    return tuple(result)

def word_counts(rows, vocabulary=()):
    with _tokenizer_lock:
        return _word_counts(rows, vocabulary)


def _word_counts(rows, vocabulary=()):
    global _tokenizer, _vocabulary
    selected = tuple(sorted({w for w in vocabulary if isinstance(w,str) and 1<len(w)<=100}))
    if _tokenizer is None or selected != _vocabulary:
        import jieba
        jieba.setLogLevel(logging.ERROR)
        _tokenizer = jieba.Tokenizer()
        _tokenizer.initialize()
        for word in selected: _tokenizer.add_word(word, freq=1000000)
        _vocabulary = selected
        _tokens.cache_clear()
    counts, spellings = Counter(), {}
    for row in rows:
        for token in _tokens(row['text']):
            key = token.casefold(); counts[key] += 1; spellings.setdefault(key, token)
    total = sum(counts.values())
    return [{'name': spellings[k], 'count': n, 'percent': round(n*100/total, 1)} for k,n in counts.most_common(12)], total


def app_counts(rows, limit=5):
    counts = Counter(r['application'] for r in rows if r.get('application'))
    known = sum(counts.values())
    total = len(rows)
    top = counts.most_common(limit)
    other = known - sum(n for _,n in top)
    if other: top.append(('其他已知应用', other))
    if total>known: top.append(('未记录应用', total-known))
    return [{'name': k, 'count': n, 'percent': round(n*100/total, 1)} for k,n in top], known
