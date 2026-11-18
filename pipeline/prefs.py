"""ページで押された評価から、話題の好みを計算する（毎朝の台本づくりの前に使う）。

  python -m pipeline.prefs feedback.json

feedback.json には、アーティファクトのデータ（コレクション "feedback"）を一覧で読んだ結果を保存する。
各ドキュメントは {date, key, label, tags, v(1/-1/0), deep, hard} を持つ。
直近28日の評価だけを使い、次の形で表示する：
  weights  話題（タグ）ごとの重み。👍 +1、👎 -1.2、「もっと深く」+0.5
  prefer   優先する話題（重み 1.5 以上）
  avoid    控えめにする話題（重み -0.5 以下）
  deep     「もっと深く知りたい」が押された話題（土曜のまとめで深掘りする候補）
  hard     「むずかしかった」が押された話題（用語の説明を増やす）
"""
from __future__ import annotations

import datetime as dt
import json
import sys
from collections import defaultdict


def load_docs(obj) -> list[dict]:
    if isinstance(obj, dict):
        for k in ("documents", "docs", "items", "results", "rows"):
            if k in obj:
                obj = obj[k]
                break
    out = []
    for d in obj if isinstance(obj, list) else []:
        body = d.get("data", d) if isinstance(d, dict) else None
        if isinstance(body, dict) and "tags" in body:
            out.append(body)
    return out


def summarize(docs: list[dict], today: dt.date | None = None, days: int = 28) -> dict:
    today = today or dt.date.today()
    since = (today - dt.timedelta(days=days)).isoformat()
    w: dict[str, float] = defaultdict(float)
    deep, hard = [], []
    for d in docs:
        if str(d.get("date", "")) < since:
            continue
        for t in d.get("tags", []):
            w[t] += {1: 1.0, -1: -1.2}.get(d.get("v", 0), 0.0) + (0.5 if d.get("deep") else 0.0)
        if d.get("deep"):
            deep.append(f'{d.get("date")} {d.get("label")}')
        if d.get("hard"):
            hard.append(f'{d.get("date")} {d.get("label")}')
    weights = dict(sorted(w.items(), key=lambda p: -p[1]))
    return {"weights": weights, "prefer": [t for t, v in weights.items() if v >= 1.5],
            "avoid": [t for t, v in weights.items() if v <= -0.5], "deep": deep, "hard": hard,
            "note": "好み以外の重要なニュースも2〜3割は入れる（探索枠）"}


def load_path(path: str) -> list[dict]:
    """JSON ファイル1つ、または ArtifactData の out_dir（ドキュメントごとの JSON ファイル）を読む。"""
    from pathlib import Path
    p = Path(path)
    if p.is_dir():
        return load_docs([json.loads(f.read_text(encoding="utf-8")) for f in sorted(p.rglob("*.json"))])
    return load_docs(json.loads(p.read_text(encoding="utf-8")))


if __name__ == "__main__":
    print(json.dumps(summarize(load_path(sys.argv[1])), ensure_ascii=False, indent=1))
