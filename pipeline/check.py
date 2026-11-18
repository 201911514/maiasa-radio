"""事後チェック：作った音声を文字に起こし、台本の読みと照らし合わせる。

合格の条件（すべて満たすこと）
1. 用語：読み辞書に登録した言葉の読みが、聞き取り結果に含まれている
2. 数字：台本の数字（2桁以上か、万・億・兆付き）の読みが、すべて含まれている
   数字のすぐ後ろに単位（ドル・円など）があれば、数字と単位の組み合わせで含まれている
3. 全体：台本と聞き取り結果の読みの一致率が、設定値（標準 0.93）以上

億・兆の扱い：Google の文字起こしは「1158億ドル」を「1158ドル」のように億・兆を落として返すことがある
（2026-11-19 の本番で確認。速さや方式を変えても同じ）。そのため億・兆の付く数字は、
・音声には事前チェックでカタカナの読み（センヒャクゴジュウハチオクドル）を渡して、確実に読ませる
・聞き取り結果に億・兆がなくても、数字の部分と単位（1158・ドル）が合っていれば合格とする
数字そのものの読み間違い（1158→1185）や単位の取り違え（ドル→円）は、これまでどおり不合格になる。
"""
from __future__ import annotations

import re
from difflib import SequenceMatcher

from .yomi import (BIG_RE, ReadingDict, drop_big_units, hira_to_kata, kata_to_hira, nfkc, numbers_in, to_kana,
                   tokens)

# 数字のすぐ後ろの単位。ドルと円の取り違えなどは、数字だけを見ていると見逃すため、組み合わせで照合する
UNIT_RE = re.compile(r"\d[\d,]*(?:\.\d+)?[万億兆]?\s*(?:ドル|円|ユーロ|元|ポンド|ウォン|パーセント|%)")


def check_line(script_text: str, tts_text: str, heard: str, rd: ReadingDict, min_ratio: float = 0.93,
               yomi: dict[str, str] | None = None) -> dict:
    """yomi: その行で指定した読み。文字起こしが同じ漢字で返したときは、指定した読みで聞こえたとみなす
    （漢字からはどちらの読みで話したか分からないため。ひらがなや別の漢字で返れば食い違いとして検出できる）。"""
    expected = to_kana(tts_text, rd)
    script_yomi = nfkc(script_text)
    for word, reading in sorted((yomi or {}).items(), key=lambda p: -len(p[0])):
        heard = heard.replace(word, kata_to_hira(reading))
        script_yomi = script_yomi.replace(word, kata_to_hira(reading))
    got = to_kana(heard, rd)
    sm = SequenceMatcher(None, expected, got, autojunk=False)
    ratio = sm.ratio()
    notes: list[str] = []
    if BIG_RE.search(script_yomi):  # 億・兆を落とした聞き取りも正解の一つとして比べる
        alt_ratio = SequenceMatcher(None, to_kana(drop_big_units(script_yomi), rd), got, autojunk=False).ratio()
        if alt_ratio > ratio:
            ratio = alt_ratio
    issues: list[dict] = []
    for e in rd.find(script_text):
        if e.reading not in got:
            issues.append({"type": "用語", "word": e.forms[0], "expected": e.reading})
    for raw, reading in numbers_in(script_text):
        if reading in got:
            continue
        if BIG_RE.search(raw) and to_kana(drop_big_units(raw), rd) in got:
            notes.append(f"{raw}：億・兆は文字起こしで落ちたため、数字の部分で確認")
            continue
        issues.append({"type": "数字", "word": raw, "expected": reading})
    for m in UNIT_RE.finditer(nfkc(script_text)):
        raw = m.group(0)
        reading = to_kana(raw, rd)
        if reading in got or (BIG_RE.search(raw) and to_kana(drop_big_units(raw), rd) in got):
            continue
        issues.append({"type": "数字と単位", "word": raw, "expected": reading})
    if ratio < min_ratio:
        issues.append({"type": "全体", "ratio": round(ratio, 3), "min": min_ratio})
    diff = [
        {"expected": expected[i1:i2], "heard": got[j1:j2], "range": [i1, i2]}
        for op, i1, i2, j1, j2 in sm.get_opcodes() if op != "equal"
    ]
    return {"ok": not issues, "ratio": round(ratio, 3), "issues": issues, "diff": diff, "notes": notes,
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
