"""アレクサ（フラッシュニュース）用のフィードを作り、GitHub Pages（gh-pages ブランチ）に置く。

  python -m pipeline.feed 2026-11-19 --push          # 公開OKの回を載せる
  python -m pipeline.feed 2026-11-19 --held --push   # 公開保留の日：「今日はお休み」の短いお知らせを載せる

出力（build/public/）
  feed.json         フラッシュニュースのフィード（最新の1回だけ。アレクサは15分ごとに見に来る）
  audio/<日付>.mp3   アレクサ用の音声（音量を -14 LUFS にそろえた 128kbps の MP3）
  index.html        説明ページ（最小限）
  .nojekyll
--push を付けると、この中身だけで gh-pages ブランチを上書きする（履歴は残さないので、音声がたまらない）。
アレクサは公開されたURLからしか取りに行けないため、ここに置いた音声は誰でも取得できる点に注意。
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _jp(date: str) -> str:
    y, m, d = (int(x) for x in date.split("-"))
    return f"{m}月{d}日"


def _normalize(src: Path, dst: Path) -> None:
    """音量を Amazon の推奨（平均 -14 LUFS、ピーク -2 dB 以下）にそろえる。1回目で測り、2回目で合わせる。"""
    target = "I=-14:TP=-2:LRA=11"
    probe = subprocess.run(["ffmpeg", "-hide_banner", "-i", str(src), "-af", f"loudnorm={target}:print_format=json",
                            "-f", "null", "-"], check=True, capture_output=True, text=True).stderr
    m = json.loads(probe[probe.rindex("{"):probe.rindex("}") + 1])
    af = (f"loudnorm={target}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:measured_LRA={m['input_lra']}"
          f":measured_thresh={m['input_thresh']}:offset={m['target_offset']}:linear=true")
    subprocess.run(["ffmpeg", "-loglevel", "error", "-y", "-i", str(src), "-af", af,
                    "-ar", "44100", "-ac", "1", "-b:a", "128k", str(dst)], check=True)


def build(date: str, held: bool = False, root: Path = ROOT, now: dt.datetime | None = None) -> Path:
    cfg = json.loads((root / "config.json").read_text(encoding="utf-8"))
    base = cfg["feed_base_url"].rstrip("/")
    out = root / "build" / "public"
    shutil.rmtree(out, ignore_errors=True)
    (out / "audio").mkdir(parents=True)
    stamp = (now or dt.datetime.now(dt.timezone.utc)).strftime("%Y-%m-%dT%H:%M:%S.0Z")

    if held:
        item = {"uid": f"maiasa-radio-{date}-held", "updateDate": stamp, "titleText": f"{_jp(date)}の回はお休みです",
                "mainText": "毎朝5分ラジオです。今日の回は、読み間違いの確認が終わっていないため、お休みします。",
                "redirectionUrl": cfg["artifact_url"]}
    else:
        ep = json.loads((root / "site" / "data" / "episodes" / f"{date}.json").read_text(encoding="utf-8"))
        wav = root / "build" / date / "episode.wav"
        src = wav if wav.exists() else root / "site" / "audio" / f"{date}.mp3"
        if not src.exists():
            raise SystemExit(f"音声が見つかりません：{wav} も {src} もありません")
        _normalize(src, out / "audio" / f"{date}.mp3")
        item = {"uid": f"maiasa-radio-{date}", "updateDate": stamp, "titleText": ep["title"], "mainText": "",
                "streamUrl": f"{base}/audio/{date}.mp3", "redirectionUrl": cfg["artifact_url"]}

    (out / "feed.json").write_text(json.dumps([item], ensure_ascii=False, indent=1), encoding="utf-8")
    (out / ".nojekyll").write_text("", encoding="utf-8")
    (out / "index.html").write_text(
        "<!doctype html><meta charset=\"utf-8\"><title>毎朝5分ラジオ</title>"
        "<p>毎朝5分ラジオのアレクサ用フィードです（<a href=\"feed.json\">feed.json</a>）。</p>", encoding="utf-8")
    return out


def push(out: Path, date: str, root: Path = ROOT) -> None:
    """build/public の中身だけで gh-pages ブランチを上書きする。"""
    url = subprocess.run(["git", "-C", str(root), "remote", "get-url", "origin"], check=True,
                         capture_output=True, text=True).stdout.strip()
    git = ["git", "-C", str(out), "-c", "user.name=Claude", "-c", "user.email=noreply@anthropic.com"]
    shutil.rmtree(out / ".git", ignore_errors=True)
    subprocess.run(git + ["init", "-q", "-b", "gh-pages"], check=True)
    subprocess.run(git + ["add", "-A"], check=True)
    subprocess.run(git + ["commit", "-q", "-m", f"アレクサ用フィード {date}"], check=True)
    subprocess.run(git + ["push", "-q", "-f", url, "gh-pages"], check=True)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="毎朝5分ラジオ：アレクサ用のフィードを作る")
    ap.add_argument("date")
    ap.add_argument("--held", action="store_true", help="公開保留の日（お休みのお知らせを載せる）")
    ap.add_argument("--push", action="store_true", help="gh-pages ブランチに送る")
    a = ap.parse_args(argv)
    out = build(a.date, a.held)
    if a.push:
        push(out, a.date)
    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    print(f"フィード：{cfg['feed_base_url'].rstrip('/')}/feed.json" + ("（送信済み）" if a.push else "（未送信）"))


if __name__ == "__main__":
    main()
