"""公開前ゲート：事前チェック → 音声合成 → 文字起こし → 照合 → 合格した回だけ公開。

使い方
  python -m pipeline.gate episodes/2026-11-05.json                 # 本番（Google TTS + config.json の文字起こし）
  python -m pipeline.gate episodes/2026-11-05.json --stt google    # 文字起こしを Google STT にする
  python -m pipeline.gate episodes/2026-11-05.json --prepare-only  # 事前チェックだけ
  python -m pipeline.gate episodes/2026-11-05.json --simulate tests/fixtures/simulated_2026-11-05.json
                                                                   # 音声なしで判定の流れを試す

終了コード
  0 = 公開してよい（build/ に episode.wav と report.json）
  2 = 公開保留（作り直しても直らない行がある。report.json の failed を人が確認）
  3 = 事前チェックで止めた（読み未登録・要確認の言葉がある）
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .check import check_line, fix_text
from .prepare import prepare_episode
from .yomi import ReadingDict

ROOT = Path(__file__).resolve().parent.parent


def run(ep_path: Path, cfg: dict, rd: ReadingDict, tts=None, stt=None, simulate: dict | None = None,
        out_dir: Path | None = None, prepare_only: bool = False) -> tuple[int, dict]:
    ep = json.loads(ep_path.read_text(encoding="utf-8"))
    prep = prepare_episode(ep, rd)
    report: dict = {"episode": ep.get("date"), "prepare": prep, "lines": [], "failed": []}
    if not prep["ok"] and cfg.get("strict_prepare", True):
        report["status"] = "事前チェックで停止"
        return 3, report
    if prepare_only:
        report["status"] = "事前チェックのみ"
        return 0, report

    audio_parts = []
    for line in prep["lines"]:
        text, attempts = line["tts_text"], []
        for n in range(cfg["max_attempts"]):
            if simulate is not None:
                tries = simulate.get(str(line["i"]), [line["text"]])
                heard, wav = tries[min(n, len(tries) - 1)], None
            else:
                wav = tts.synthesize(text, line["speaker"])
                heard = stt.transcribe(wav)
            res = check_line(line["text"], text, heard, rd, cfg["min_ratio"], ep["lines"][line["i"]].get("yomi"))
            attempts.append({"tts_text": text, "heard": heard, **{k: res[k] for k in ("ok", "ratio", "issues")}})
            if res["ok"]:
                break
            text = fix_text(text, res, rd)  # 食い違った部分を読み（ひらがな）にして作り直す
        report["lines"].append({"i": line["i"], "speaker": line["speaker"], "text": line["text"],
                                "ok": attempts[-1]["ok"], "attempts": attempts})
        if attempts[-1]["ok"]:
            audio_parts.append(wav)
        else:
            report["failed"].append(line["i"])

    passed = not report["failed"]
    report["status"] = "公開OK" if passed else "公開保留"
    if passed and out_dir and simulate is None:
        from .backends import concat_wavs
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "episode.wav").write_bytes(concat_wavs(audio_parts))
    return (0 if passed else 2), report


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="毎朝5分ラジオ：公開前の音声チェック")
    ap.add_argument("episode")
    ap.add_argument("--stt", choices=["google", "whisper"], default=None, help="省略時は config.json の stt")
    ap.add_argument("--simulate", help="聞き取り結果のテスト用ファイル（音声を作らずに判定を試す）")
    ap.add_argument("--prepare-only", action="store_true")
    ap.add_argument("--out", default=None)
    a = ap.parse_args(argv)

    cfg = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))
    rd = ReadingDict.load(ROOT / "reading_dict.json")
    ep_path = Path(a.episode)
    out_dir = Path(a.out) if a.out else ROOT / "build" / ep_path.stem
    tts = stt = simulate = None
    if a.simulate:
        simulate = json.loads(Path(a.simulate).read_text(encoding="utf-8"))
    elif not a.prepare_only:
        from .backends import GoogleSTT, GoogleTTS, WhisperSTT
        tts = GoogleTTS(cfg["voices"], cfg.get("speaking_rate", 1.0))
        engine = a.stt or cfg.get("stt", "whisper")
        stt = WhisperSTT(cfg.get("whisper_model", "medium")) if engine == "whisper" else GoogleSTT()

    code, report = run(ep_path, cfg, rd, tts, stt, simulate, out_dir, a.prepare_only)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{report['status']}（終了コード {code}）  レポート: {out_dir / 'report.json'}")
    for i, f in report["prepare"]["blocking"]:
        print(f"  事前チェック 行{i}: {f['word']}（{f['type']}・{f['status']}）")
    for i in report["failed"]:
        last = report["lines"][i]["attempts"][-1]
        print(f"  不合格 行{i}: {[x['type'] for x in last['issues']]}  聞き取り: {last['heard']}")
    return code


if __name__ == "__main__":
    sys.exit(main())
