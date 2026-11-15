"""読みのユーティリティ。

台本と、音声を文字に起こした結果の両方を、同じルールでカタカナの「読み」にそろえる。
- 読み辞書（英字・固有名詞など）を先に当てる
- 数字はルールでカタカナに直す（例: 200億 → ニヒャクオク）
- 残りは形態素解析（fugashi + unidic-lite）の読みを使う
"""
from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

DIGIT = ["", "イチ", "ニ", "サン", "ヨン", "ゴ", "ロク", "ナナ", "ハチ", "キュウ"]
DIGIT_READ = ["ゼロ", "イチ", "ニ", "サン", "ヨン", "ゴ", "ロク", "ナナ", "ハチ", "キュウ"]
LETTER = {
    "A": "エー", "B": "ビー", "C": "シー", "D": "ディー", "E": "イー", "F": "エフ", "G": "ジー",
    "H": "エイチ", "I": "アイ", "J": "ジェー", "K": "ケー", "L": "エル", "M": "エム", "N": "エヌ",
    "O": "オー", "P": "ピー", "Q": "キュー", "R": "アール", "S": "エス", "T": "ティー", "U": "ユー",
    "V": "ブイ", "W": "ダブリュー", "X": "エックス", "Y": "ワイ", "Z": "ゼット",
}
UNIT_POW = {"万": 4, "億": 8, "兆": 12}
NUM_RE = re.compile(r"(\d[\d,]*)(?:\.(\d+))?([万億兆])?")


def nfkc(s: str) -> str:
    return unicodedata.normalize("NFKC", s)


def hira_to_kata(s: str) -> str:
    return "".join(chr(ord(c) + 0x60) if "ぁ" <= c <= "ゖ" else c for c in s)


def kata_to_hira(s: str) -> str:
    return "".join(chr(ord(c) - 0x60) if "ァ" <= c <= "ヶ" else c for c in s)


def _under_10000(n: int) -> str:
    s = ""
    th, n = divmod(n, 1000)
    if th:
        s += {1: "セン", 3: "サンゼン", 8: "ハッセン"}.get(th, DIGIT[th] + "セン")
    hu, n = divmod(n, 100)
    if hu:
        s += {1: "ヒャク", 3: "サンビャク", 6: "ロッピャク", 8: "ハッピャク"}.get(hu, DIGIT[hu] + "ヒャク")
    te, n = divmod(n, 10)
    if te:
        s += "ジュウ" if te == 1 else DIGIT[te] + "ジュウ"
    if n:
        s += DIGIT[n]
    return s


def int_to_kana(n: int) -> str:
    """整数をカタカナの読みにする（兆まで）。"""
    if n == 0:
        return "ゼロ"
    s = ""
    for base, name in ((10**12, "チョウ"), (10**8, "オク"), (10**4, "マン")):
        q, n = divmod(n, base)
        if q:
            head = _under_10000(q)
            if name == "チョウ":  # 一兆→イッチョウ、八兆→ハッチョウ、十兆→ジュッチョウ
                for a, b in (("イチ", "イッ"), ("ハチ", "ハッ"), ("ジュウ", "ジュッ")):
                    if head.endswith(a):
                        head = head[: -len(a)] + b
                        break
            s += head + name
    return s + _under_10000(n)


def number_to_kana(m: re.Match) -> str:
    whole = int(m.group(1).replace(",", ""))
    frac, unit = m.group(2), m.group(3)
    if frac:
        r = int_to_kana(whole) + "テン" + "".join(DIGIT_READ[int(d)] for d in frac)
        return r + ({"万": "マン", "億": "オク", "兆": "チョウ"}[unit] if unit else "")
    if unit:
        return int_to_kana(whole * 10 ** UNIT_POW[unit])
    return int_to_kana(whole)


def numbers_in(text: str, min_digits: int = 2) -> list[tuple[str, str]]:
    """チェック対象の数字（2桁以上か、万・億・兆付き）と、その読み。"""
    out = []
    for m in NUM_RE.finditer(nfkc(text)):
        if len(m.group(1).replace(",", "")) >= min_digits or m.group(3):
            out.append((m.group(0), number_to_kana(m)))
    return out


@dataclass
class Entry:
    reading: str          # カタカナ
    forms: list[str]      # 台本や聞き取り結果に出てくる書き方


class ReadingDict:
    """読み辞書。英字の語は大文字小文字を区別せず、前後が英字でないときだけ置き換える。"""

    def __init__(self, entries: list[Entry]):
        self.entries = entries
        pairs = [(f, e) for e in entries for f in e.forms]
        pairs.sort(key=lambda p: -len(p[0]))
        self._pairs = []
        for form, e in pairs:
            if form.isascii():
                pat = re.compile(r"(?<![A-Za-z])" + re.escape(form) + r"(?![A-Za-z])", re.IGNORECASE)
            else:
                pat = re.compile(re.escape(form))
            self._pairs.append((pat, e))

    @classmethod
    def load(cls, path: str | Path) -> "ReadingDict":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return cls([Entry(hira_to_kata(d["reading"]), d["forms"]) for d in data["entries"]])

    def apply(self, text: str) -> str:
        for pat, e in self._pairs:
            text = pat.sub(e.reading, text)
        return text

    def find(self, text: str) -> list[Entry]:
        found = []
        for pat, e in self._pairs:
            if e not in found and pat.search(text):
                found.append(e)
        return found


@lru_cache(maxsize=1)
def tagger():
    import fugashi  # 遅延読み込み（テスト以外では必須）
    return fugashi.Tagger()


def token_kana(surface: str, feature) -> str:
    k = getattr(feature, "kana", None)
    if k and k != "*":
        return k
    if re.fullmatch(r"[ァ-ヴー]+", surface):
        return surface
    if re.fullmatch(r"[ぁ-ゖー]+", surface):
        return hira_to_kata(surface)
    if re.fullmatch(r"[A-Z]{2,6}", surface):
        return "".join(LETTER[c] for c in surface)
    if re.fullmatch(r"[A-Za-z][A-Za-z0-9]*", surface):
        return surface.lower()
    return ""  # 句読点・記号など


TSU = {1: "ヒトツ", 2: "フタツ", 3: "ミッツ", 4: "ヨッツ", 5: "イツツ", 6: "ムッツ", 7: "ナナツ", 8: "ヤッツ", 9: "ココノツ"}
FUN_RE = re.compile(r"(?<![\d.,])(\d+)分")
TSU_RE = re.compile(r"(?<![\d.,])([1-9])つ")


def minutes_to_kana(n: int) -> str:
    """〜分の読み（1分=イップン、3分=サンプン、5分=ゴフン、10分=ジュップン）。"""
    head = int_to_kana(n)
    last = n % 10
    if last in (1, 6, 8) or (last == 0 and n % 100 != 0 and head.endswith("ジュウ")):
        for a, b in (("イチ", "イッ"), ("ロク", "ロッ"), ("ハチ", "ハッ"), ("ジュウ", "ジュッ")):
            if head.endswith(a):
                return head[: -len(a)] + b + "プン"
    if last in (3, 4):
        return head + "プン"
    return head + "フン"


def preprocess(text: str, rd: ReadingDict | None) -> str:
    t = nfkc(text)
    if rd:
        t = rd.apply(t)
    # 聞き取り結果が「一分」「三つ」のような漢数字で返ってきても、同じ読みにそろえる
    t = re.sub(r"(?<![一-龥])([一二三四五六七八九])(分|つ)", lambda m: str("一二三四五六七八九".index(m.group(1)) + 1) + m.group(2), t)
    t = FUN_RE.sub(lambda m: minutes_to_kana(int(m.group(1))), t)
    t = TSU_RE.sub(lambda m: TSU[int(m.group(1))], t)
    return NUM_RE.sub(number_to_kana, t)


def tokens(text: str, rd: ReadingDict | None = None) -> list[tuple[str, str, object]]:
    """(表記, 読み, 素性) のリスト。辞書と数字の置き換えをしたあとで解析する。"""
    return [(w.surface, token_kana(w.surface, w.feature), w.feature) for w in tagger()(preprocess(text, rd))]


def to_kana(text: str, rd: ReadingDict | None = None) -> str:
    return hira_to_kata("".join(k for _, k, _ in tokens(text, rd)))
