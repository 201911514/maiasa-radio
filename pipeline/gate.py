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

    audio_parts, failed_audio = [], {}
    for line in prep["lines"]:
        text, attempts, wav = line["tts_text"], [], None
        yomi = ep["lines"][line["i"]].get("yomi")
        for n in range(cfg["max_attempts"]):
            # 最後の作り直しだけは、話す速さを retry_slow_rate（標準 1.0 倍）に落として、はっきり読ませる。
            # 速い読み上げで文字起こしが聞き間違え、正しい回まで公開保留になるのを減らすため（2026-11-23）
            slow = n == cfg["max_attempts"] - 1 and n > 0 and cfg.get("retry_slow_rate")
            rate = cfg["retry_slow_rate"] if slow else None
            if simulate is not None:
                tries = simulate.get(str(line["i"]), [line["text"]])
                heard, wav = tries[min(n, len(tries) - 1)], None
            else:
                wav = tts.synthesize(text, line["speaker"], rate=rate)
                heard = stt.transcribe(wav)
            res = check_line(line["text"], text, heard, rd, cfg["min_ratio"], yomi)
            alt = None
            if not res["ok"] and wav is not None and hasattr(stt, "transcribe_alt"):
                heard_alt = stt.transcribe_alt(wav)  # 同じ音声を別の方式で聞き直す
                if heard_alt is not None:
                    res_alt = check_line(line["text"], text, heard_alt, rd, cfg["min_ratio"], yomi)
                    alt = {"heard": heard_alt, **{k: res_alt[k] for k in ("ok", "ratio", "issues")}}
                    if res_alt["ok"]:
                        res = res_alt  # heard は1回目の聞き取りのまま残し、alt に合格した聞き取りを残す
            attempts.append({"tts_text": text, "heard": heard, "alt": alt, "rate": rate or cfg.get("speaking_rate", 1.0),
                             **{k: res[k] for k in ("ok", "ratio", "issues")}})
            if res["ok"]:
                break
            text = fix_text(text, res, rd)  # 食い違った部分を読み（ひらがな）にして作り直す
        report["lines"].append({"i": line["i"], "speaker": line["speaker"], "text": line["text"],
                                "ok": attempts[-1]["ok"], "attempts": attempts})
        audio_parts.append(wav)
        if not attempts[-1]["ok"]:
            report["failed"].append(line["i"])
            failed_audio[line["i"]] = wav

    passed = not report["failed"]
    report["status"] = "公開OK" if passed else "公開保留"
    if out_dir and simulate is None:
        from .backends import concat_wavs, wav_seconds
        out_dir.mkdir(parents=True, exist_ok=True)
        # 字幕を音声に合わせるため、各行の開始・終了（秒）を記録する（行の間の無音 0.35 秒込み）
        t, report["timings"] = 0.0, []
        for w in audio_parts:
            d = wav_seconds(w)
            report["timings"].append([round(t, 2), round(t + d, 2)])
            t += d + 0.35
        report["duration"] = round(t - 0.35, 2)
        if passed:
            (out_dir / "episode.wav").write_bytes(concat_wavs(audio_parts))
        else:  # 公開はしないが、人が聞いて確かめられるよう確認用の音声を残す
            (out_dir / "review.wav").write_bytes(concat_wavs(audio_parts))
            for i, w in failed_audio.items():
                (out_dir / f"line-{i:02d}.wav").write_bytes(w)
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
    if report["failed"] and not a.simulate:
        print(f"  確認用の音声: {out_dir / 'review.wav'}（不合格の行は line-XX.wav）")
    return code


if __name__ == "__main__":
    sys.exit(main())
