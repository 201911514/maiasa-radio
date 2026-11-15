"""事後チェック：作った音声を文字に起こし、台本の読みと照らし合わせる。

合格の条件（すべて満たすこと）
1. 用語：読み辞書に登録した言葉の読みが、聞き取り結果に含まれている
2. 数字：台本の数字（2桁以上か、万・億・兆付き）の読みが、すべて含まれている
3. 全体：台本と聞き取り結果の読みの一致率が、設定値（標準 0.93）以上
"""
from __future__ import annotations

from difflib import SequenceMatcher

from .yomi import ReadingDict, hira_to_kata, kata_to_hira, numbers_in, to_kana, tokens


def check_line(script_text: str, tts_text: str, heard: str, rd: ReadingDict, min_ratio: float = 0.93,
               yomi: dict[str, str] | None = None) -> dict:
    """yomi: その行で指定した読み。文字起こしが同じ漢字で返したときは、指定した読みで聞こえたとみなす
    （漢字からはどちらの読みで話したか分からないため。ひらがなや別の漢字で返れば食い違いとして検出できる）。"""
    expected = to_kana(tts_text, rd)
    for word, reading in sorted((yomi or {}).items(), key=lambda p: -len(p[0])):
        heard = heard.replace(word, kata_to_hira(reading))
    got = to_kana(heard, rd)
    sm = SequenceMatcher(None, expected, got, autojunk=False)
    ratio = sm.ratio()
    issues: list[dict] = []
    for e in rd.find(script_text):
        if e.reading not in got:
            issues.append({"type": "用語", "word": e.forms[0], "expected": e.reading})
    for raw, reading in numbers_in(script_text):
        if reading not in got:
            issues.append({"type": "数字", "word": raw, "expected": reading})
    if ratio < min_ratio:
        issues.append({"type": "全体", "ratio": round(ratio, 3), "min": min_ratio})
    diff = [
        {"expected": expected[i1:i2], "heard": got[j1:j2], "range": [i1, i2]}
        for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"
    ]
    return {"ok": not issues, "ratio": round(ratio, 3), "issues": issues, "diff": diff,
            "expected_kana": expected, "heard_kana": got}


def fix_text(tts_text: str, result: dict, rd: ReadingDict) -> str:
    """作り直し用：食い違った部分の漢字を、正しい読み（ひらがな）に置き換えた文を返す。"""
    ranges = [d["range"] for d in result["diff"]]
    out, pos = [], 0
    for surface, kana, _ in tokens(tts_text, rd):
        start, end = pos, pos + len(hira_to_kata(kana))
        pos = end
        hit = any(start < r[1] and r[0] < end for r in ranges) or any(r[0] == r[1] == start for r in ranges)
        if hit and kana and any("一" <= c <= "龥" or c.isdigit() for c in surface):
            out.append(kata_to_hira(kana))
        else:
            out.append(surface)
    return "".join(out)
