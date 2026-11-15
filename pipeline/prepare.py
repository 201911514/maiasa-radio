"""事前チェック：音声を作る前に、読み間違えやすい言葉を見つけて読みを決める。

見つけるもの
- 英字の語（Claude、CBS など）……読み辞書にあれば置き換え、なければ「未登録」
- 数字（200億、1,200 など）……ルールで読みを出す（音声にはそのまま渡し、事後チェックで確認）
- 読み分けが必要な言葉（今日・行った・市場 など）……台本側で読みを指定していなければ「要確認」
- 辞書にない語……読みが取れない語は「要確認」

台本の各行には "yomi": {"表記": "よみ"} を付けて、その行だけの読みを指定できる。
毎朝の自動実行では、Claude がこの指定と読み辞書への追加を行ってから音声を作る。
"""
from __future__ import annotations

import re

from .yomi import ReadingDict, hira_to_kata, kata_to_hira, nfkc, numbers_in, tagger

# 読み分けが必要な言葉（形態素の表記で照合）。ニュース台本でよく出るものから始め、増やしていく。
HOMOGRAPHS: dict[str, list[str]] = {
    "今日": ["きょう", "こんにち"], "明日": ["あした", "あす", "みょうにち"], "昨日": ["きのう", "さくじつ"],
    "一日": ["いちにち", "ついたち"], "行っ": ["いっ", "おこなっ"], "市場": ["しじょう", "いちば"],
    "一時": ["いちじ", "いっとき"], "十分": ["じゅうぶん", "じゅっぷん"], "大勢": ["おおぜい", "たいせい"],
    "方": ["ほう", "かた"], "他": ["ほか", "た"], "何": ["なに", "なん"], "人気": ["にんき", "ひとけ"],
    "上手": ["じょうず", "かみて"], "最中": ["さいちゅう", "もなか"], "大事": ["だいじ", "おおごと"],
    "生物": ["せいぶつ", "なまもの"], "分別": ["ぶんべつ", "ふんべつ"], "目下": ["もっか", "めした"],
    "見物": ["けんぶつ", "みもの"], "末期": ["まっき", "まつご"], "色紙": ["しきし", "いろがみ"],
    "風車": ["ふうしゃ", "かざぐるま"], "後": ["あと", "ご", "のち"], "間": ["あいだ", "ま", "かん"],
}
LATIN_RE = re.compile(r"[A-Za-z][A-Za-z0-9.\-]*[A-Za-z0-9]|[A-Za-z]")
# 1桁の数字のあとに来ると読みが変わる助数詞（1分=いっぷん、1本=いっぽん、6杯=ろっぱい など）
COUNTER_RE = re.compile(r"(?<![\d.,])[1-9][分本杯匹階発軒]")


def prepare_line(text: str, rd: ReadingDict, yomi: dict[str, str] | None = None) -> dict:
    yomi = yomi or {}
    flags: list[dict] = []
    t = nfkc(text)

    # 1) 行ごとの読み指定を先に当てる（音声にはひらがなで渡す）
    tts_text = t
    for word, reading in sorted(yomi.items(), key=lambda p: -len(p[0])):
        tts_text = tts_text.replace(word, kata_to_hira(reading))
        flags.append({"word": word, "type": "読み分け", "reading": hira_to_kata(reading), "status": "指定済み"})

    # 2) 英字
    for m in LATIN_RE.finditer(tts_text):
        w = m.group(0)
        hit = rd.find(w)
        if hit:
            flags.append({"word": w, "type": "英字", "reading": hit[0].reading, "status": "辞書で解決"})
        else:
            flags.append({"word": w, "type": "英字", "reading": "", "status": "未登録"})
    tts_text = rd.apply(tts_text)

    # 3) 数字
    for raw, reading in numbers_in(t):
        flags.append({"word": raw, "type": "数字", "reading": reading, "status": "自動（事後チェックで確認）"})

    # 4) 読み分けが必要な言葉・読みが取れない言葉
    for w in tagger()(tts_text):
        s = w.surface
        if s in HOMOGRAPHS and not any(f["word"].startswith(s) for f in flags if f["status"] == "指定済み"):
            flags.append({"word": s, "type": "読み分け", "reading": "／".join(HOMOGRAPHS[s]), "status": "要確認"})
        k = getattr(w.feature, "kana", None)
        if (not k or k == "*") and re.search(r"[一-龥]", s):
            flags.append({"word": s, "type": "辞書にない語", "reading": "", "status": "要確認"})

    # 5) 数字＋助数詞（読みが変わるもの）。行の読み指定があれば解決済み
    for m in COUNTER_RE.finditer(t):
        w = m.group(0)
        if w in yomi:
            continue
        flags.append({"word": w, "type": "数字＋助数詞", "reading": "", "status": "要確認"})

    seen, uniq = set(), []
    for f in flags:
        key = (f["word"], f["type"], f["status"])
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    return {"text": text, "tts_text": tts_text, "flags": uniq}


def prepare_episode(ep: dict, rd: ReadingDict) -> dict:
    lines = []
    for i, line in enumerate(ep["lines"]):
        r = prepare_line(line["text"], rd, line.get("yomi"))
        r.update({"i": i, "speaker": line["speaker"], "chapter": line.get("chapter", "")})
        lines.append(r)
    blocking = [(l["i"], f) for l in lines for f in l["flags"] if f["status"] in ("未登録", "要確認")]
    return {"lines": lines, "blocking": blocking, "ok": not blocking}
