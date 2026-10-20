import importlib.util
import json
from pathlib import Path

path=Path(__file__).resolve().parents[2]/'ime-channel-test/personalization.py'
if not path.exists():
    path=Path(__file__).resolve().parents[1]/'integration/personalization.py'
spec=importlib.util.spec_from_file_location('word_corrections',path)
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def make(tmp_path, words, enabled=True):
    p=tmp_path/'wordbook.json';p.write_text(json.dumps({'enabled':enabled,'words':words}))
    return module.Personalizer(p)


def test_explicit_correction_preserves_unrelated_digits_and_negation(tmp_path):
    p=make(tmp_path,[{'term':'小哈','aliases':['小蛤']}])
    assert p.apply('小蛤说明天10点不能开会。')=='小哈说明天10点不能开会。'


def test_disabled_and_missing_rules_leave_text_identical(tmp_path):
    p=make(tmp_path,[{'term':'小哈','aliases':['小蛤']}],False)
    assert p.apply('小蛤')=='小蛤'
    assert module.Personalizer(tmp_path/'missing.json').apply('原文')=='原文'


def test_conflicting_alias_is_not_silently_reassigned(tmp_path):
    p=make(tmp_path,[{'term':'甲','aliases':['共同误词']},{'term':'乙','aliases':['共同误词']}])
    assert p.apply('共同误词')=='共同误词'


def test_replacements_are_literal_single_pass_and_longest_first(tmp_path):
    p=make(tmp_path,[{'term':'准确长词','aliases':['长误词']},{'term':'不应二次替换','aliases':['准确长词']},{'term':'短词','aliases':['误词']},{'term':'正则字符','aliases':['a+b']}])
    assert p.apply('长误词 a+b')=='准确长词 正则字符'


def test_ascii_alias_requires_token_boundaries(tmp_path):
    p=make(tmp_path,[{'term':'AI','aliases':['ai']}])
    assert p.apply('ai chair')=='AI chair'


def test_malformed_dictionary_is_safe(tmp_path):
    p=tmp_path/'bad.json';p.write_text('{')
    assert module.Personalizer(p).apply('原文')=='原文'
