"""ページ用のデータを作る：台本＋公開前チェックの結果 → site/data と site/audio。

  python -m pipeline.site 2026-11-19                      # 合格した回を載せる
  python -m pipeline.site 2026-11-19 --held "行24が直らず"  # 公開保留：音声は載せず、ページに「確認待ち」を出す

使うもの: episodes/<日付>.json（台本）、build/<日付>/report.json と episode.wav（公開前チェックの結果）
出力
  site/data/index.json            番組表と、これまでの回の一覧（リポジトリに入れる）
  site/data/episodes/<日付>.json   1回分：台本・字幕の時刻・スライド・クイズ・出典（リポジトリに入れる）
  site/audio/<日付>.mp3            音声（リポジトリには入れない）
最後の行に、アーティファクトに公開するときの files 指定（JSON）を表示する。
古い音声（keep_audio_days より前）は公開先から消す指定（null）も含める。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
JST = dt.timezone(dt.timedelta(hours=9))


def _read(p: Path):
    return json.loads(p.read_text(encoding="utf-8"))


def _write(p: Path, obj) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=1), encoding="utf-8")


def build(date: str, held_reason: str | None = None) -> dict:
    cfg = _read(ROOT / "config.json")
    ep = _read(ROOT / "episodes" / f"{date}.json")
    day = dt.date.fromisoformat(date)
    sched = cfg["schedule"][day.weekday()]
    idx_path = ROOT / "site" / "data" / "index.json"
    index = _read(idx_path) if idx_path.exists() else {"episodes": []}
    index["schedule"] = cfg["schedule"]
    index["listen_time"] = cfg.get("listen_time", "05:30")

    entry = {"date": date, "weekday": sched["day"], "theme": ep.get("theme", sched["theme"]),
             "title": ep["title"], "subtitle": ep.get("subtitle", ""),
             "topics": [c["label"] for c in ep["chapters"] if c.get("tags")]}
    files: dict[str, str | None] = {"data/index.json": str(idx_path)}

    if held_reason is None:
        rep = _read(ROOT / "build" / date / "report.json")
        if rep.get("status") != "公開OK" or "timings" not in rep:
            raise SystemExit("公開前チェックに合格していないため、ページに載せられません（--held を使う）")
        ch_index = {c["key"]: i for i, c in enumerate(ep["chapters"])}
        lines = [{"c": ch_index[l["chapter"]], "s": l["speaker"], "t": l["text"], "start": t[0], "end": t[1]}
                 for l, t in zip(ep["lines"], rep["timings"])]
        words = {(f["word"], f["type"]) for l in rep["prepare"]["lines"] for f in l["flags"]}
        redo = sum(1 for l in rep["lines"] if len(l["attempts"]) > 1 or any(a.get("alt") for a in l["attempts"]))
        check = {"status": "公開OK", "lines": len(lines), "rechecked": redo, "words": len(words)}
        data = {**entry, "duration": rep["duration"], "audio": f"audio/{date}.mp3",
                "chapters": ep["chapters"], "lines": lines, "quiz": ep.get("quiz"), "check": check}
        ep_path = ROOT / "site" / "data" / "episodes" / f"{date}.json"
        _write(ep_path, data)
        mp3 = ROOT / "site" / "audio" / f"{date}.mp3"
        mp3.parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(ROOT / "build" / date / "episode.wav"),
                        "-ac", "1", "-b:a", "64k", str(mp3)], check=True)
        entry.update({"status": "公開OK", "duration": rep["duration"], "audio": True, "check": check})
        files[f"data/episodes/{date}.json"] = str(ep_path)
        files[f"audio/{date}.mp3"] = str(mp3)
    else:
        entry.update({"status": "公開保留", "reason": held_reason, "audio": False})

    index["episodes"] = sorted([e for e in index["episodes"] if e["date"] != date] + [entry],
                               key=lambda e: e["date"], reverse=True)
    cutoff = (day - dt.timedelta(days=cfg.get("keep_audio_days", 14))).isoformat()
    for e in index["episodes"]:
        if e.get("audio") and e["date"] < cutoff:
            files[f"audio/{e['date']}.mp3"] = None  # 公開先から古い音声を消す（台本データは残す）
            e["audio"] = False
    index["updated"] = dt.datetime.now(JST).isoformat(timespec="minutes")
    _write(idx_path, index)
    return files


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="毎朝5分ラジオ：ページ用のデータを作る")
    ap.add_argument("date")
    ap.add_argument("--held", metavar="理由", help="公開保留にする（音声は載せない）")
    a = ap.parse_args(argv)
    files = build(a.date, a.held)
    print(json.dumps(files, ensure_ascii=False))


if __name__ == "__main__":
    main()
