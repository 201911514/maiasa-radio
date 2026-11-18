"""判定ロジックのテスト（音声合成・文字起こしなしで実行できる）。

  python -m unittest discover -s tests -v
"""
import json
import unittest
from pathlib import Path

from pipeline.check import check_line, fix_text
from pipeline.gate import run
from pipeline.prepare import prepare_line
from pipeline.yomi import ReadingDict, int_to_kana, minutes_to_kana, to_kana

ROOT = Path(__file__).resolve().parent.parent
RD = ReadingDict.load(ROOT / "reading_dict.json")
CFG = json.loads((ROOT / "config.json").read_text(encoding="utf-8"))


class Numbers(unittest.TestCase):
    def test_int(self):
        self.assertEqual(int_to_kana(200 * 10**8), "ニヒャクオク")
        self.assertEqual(int_to_kana(1200), "センニヒャク")
        self.assertEqual(int_to_kana(110), "ヒャクジュウ")
        self.assertEqual(int_to_kana(3 * 10**12), "サンチョウ")
        self.assertEqual(int_to_kana(10**12), "イッチョウ")
        self.assertEqual(int_to_kana(8600), "ハッセンロッピャク")

    def test_minutes(self):
        self.assertEqual(minutes_to_kana(1), "イップン")
        self.assertEqual(minutes_to_kana(5), "ゴフン")
        self.assertEqual(minutes_to_kana(10), "ジュップン")

    def test_same_reading_for_digits_and_kanji(self):
        self.assertEqual(to_kana("世界の1分ニュース", RD), to_kana("世界の一分ニュース", RD))
        self.assertEqual(to_kana("200億ドル", RD), to_kana("二百億ドル", RD))


class Prepare(unittest.TestCase):
    def test_unknown_latin_blocks(self):
        r = prepare_line("Perplexityが新機能を発表", RD)
        self.assertIn(("Perplexity", "未登録"), [(f["word"], f["status"]) for f in r["flags"]])

    def test_homograph_needs_context(self):
        r = prepare_line("明日の市場に注目です", RD)
        self.assertEqual({f["word"] for f in r["flags"] if f["status"] == "要確認"}, {"明日", "市場"})

    def test_yomi_override_resolves(self):
        r = prepare_line("明日の市場に注目です", RD, {"明日": "あす", "市場": "しじょう"})
        self.assertFalse([f for f in r["flags"] if f["status"] == "要確認"])
        self.assertEqual(r["tts_text"], "あすのしじょうに注目です")


class Check(unittest.TestCase):
    def _c(self, script, heard, yomi=None):
        tts = prepare_line(script, RD, yomi)["tts_text"]
        return check_line(script, tts, heard, RD, CFG["min_ratio"])

    def test_correct_with_different_spelling_passes(self):
        r = self._c("CBSやCNBCの予測では、民主党が過半数を取る見通しです。",
                    "シービーエスやシーエヌビーシーの予測では民主党が過半数を取る見通しです")
        self.assertTrue(r["ok"], r)

    def test_misread_name_fails(self):
        r = self._c("Claudeを開発しているAnthropicが発表しました。", "クラウドを開発しているアンソロピックが発表しました。")
        self.assertFalse(r["ok"])
        self.assertEqual(r["issues"][0]["type"], "用語")

    def test_wrong_number_fails(self):
        r = self._c("目標は200億ドルです。", "目標は2000億ドルです。")
        self.assertIn("数字", [i["type"] for i in r["issues"]])

    def test_wrong_unit_fails(self):
        r = self._c("これまでに集まったのは、110億ドルほどだそうです。", "これまでに集まったのは110億円ほどだそうです")
        self.assertIn("数字と単位", [i["type"] for i in r["issues"]])

    def test_right_unit_passes(self):
        r = self._c("日本円でおよそ3兆円です。", "日本円でおよそ三兆円です")
        self.assertTrue(r["ok"], r)

    def test_skipped_phrase_fails(self):
        r = self._c("民主党が下院で過半数を取り、上院でも多数派になる見通しです。", "民主党が下院で過半数を取る見通しです。")
        self.assertIn("全体", [i["type"] for i in r["issues"]])

    def test_homograph_misread_is_caught_when_heard_in_kana(self):
        r = self._c("明日の市場に注目です。", "あすのいちばに注目です。", {"明日": "あす", "市場": "しじょう"})
        self.assertFalse(r["ok"])

    def test_fix_text_spells_out_mismatched_kanji(self):
        tts = "明日の市場に注目です。"
        r = check_line(tts, tts, "明日のいちばに注目です。", RD, CFG["min_ratio"])
        self.assertIn("しじょう", fix_text(tts, r, RD))


class Feed(unittest.TestCase):
    def _root(self, tmp: Path) -> Path:
        cfg = dict(CFG, feed_base_url="https://example.github.io/maiasa-radio", artifact_url="https://claude.ai/artifact/x")
        (tmp / "config.json").write_text(json.dumps(cfg, ensure_ascii=False), encoding="utf-8")
        return tmp

    def test_held_feed_is_text_only(self):
        import datetime as dt, tempfile
        from pipeline.feed import build
        with tempfile.TemporaryDirectory() as d:
            out = build("2026-11-19", held=True, root=self._root(Path(d)),
                        now=dt.datetime(2026, 11, 18, 19, 50, tzinfo=dt.timezone.utc))
            item = json.loads((out / "feed.json").read_text(encoding="utf-8"))[0]
            self.assertEqual(item["updateDate"], "2026-11-18T19:50:00.0Z")
            self.assertNotIn("streamUrl", item)
            self.assertIn("お休み", item["mainText"])

    def test_audio_feed_points_to_normalized_mp3(self):
        import subprocess, tempfile
        from pipeline.feed import build
        with tempfile.TemporaryDirectory() as d:
            root = self._root(Path(d))
            (root / "site/data/episodes").mkdir(parents=True)
            (root / "site/data/episodes/2026-11-19.json").write_text(json.dumps({"title": "11月19日（木） AIの回"}, ensure_ascii=False), encoding="utf-8")
            (root / "build/2026-11-19").mkdir(parents=True)
            subprocess.run(["ffmpeg", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=12",
                            str(root / "build/2026-11-19/episode.wav")], check=True)
            out = build("2026-11-19", root=root)
            item = json.loads((out / "feed.json").read_text(encoding="utf-8"))[0]
            self.assertEqual(item["streamUrl"], "https://example.github.io/maiasa-radio/audio/2026-11-19.mp3")
            self.assertEqual(item["titleText"], "11月19日（木） AIの回")
            self.assertTrue((out / "audio/2026-11-19.mp3").stat().st_size > 10000)


class Gate(unittest.TestCase):
    def test_simulated_episode_is_held(self):
        sim = json.loads((ROOT / "tests/fixtures/simulated_2026-11-05.json").read_text(encoding="utf-8"))
        code, rep = run(ROOT / "episodes/2026-11-05.json", CFG, RD, simulate=sim)
        self.assertEqual(code, 2)
        self.assertEqual(rep["failed"], [30])
        retried = {l["i"]: len(l["attempts"]) for l in rep["lines"] if len(l["attempts"]) > 1}
        self.assertEqual(retried, {12: 2, 13: 2, 24: 2, 30: 3})

    def test_clean_episode_passes(self):
        code, rep = run(ROOT / "episodes/2026-11-05.json", CFG, RD, simulate={})
        self.assertEqual(code, 0, rep["failed"])


if __name__ == "__main__":
    unittest.main()
