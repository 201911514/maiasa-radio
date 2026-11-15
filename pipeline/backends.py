"""外部の音声合成（TTS）と文字起こし（STT）。

音声合成: Google Cloud Text-to-Speech（Chirp 3 HD の声）
文字起こし: Google Cloud Speech-to-Text（標準）か、Whisper（faster-whisper、自分のマシンや GitHub Actions で無料）

認証: Text-to-Speech API と Speech-to-Text API を有効にした API キーを X-Goog-Api-Key ヘッダーで送る。
- Claude Code のクラウド環境: キーは環境の「ネットワークシークレット」に保存し、プロキシが本物のキーに差し替える
  （コード・チャット・リポジトリにキーを書かない）
- 手元のパソコン: 環境変数 GOOGLE_API_KEY で渡す
声の名前は `python -m pipeline.backends --list-voices` で確認できる。
"""
from __future__ import annotations

import base64
import io
import json
import os
import sys
import urllib.request
import wave

SAMPLE_RATE = 24000


def _headers() -> dict:
    # GOOGLE_API_KEY がなければ仮の値を送る。Claude Code の環境ではプロキシが保存済みのキーに差し替える
    return {"Content-Type": "application/json", "X-Goog-Api-Key": os.environ.get("GOOGLE_API_KEY", "set-by-proxy")}


def _post(url: str, body: dict) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=_headers())
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read())


class GoogleTTS:
    def __init__(self, voices: dict[str, str], speaking_rate: float = 1.0):
        self.voices, self.rate = voices, speaking_rate

    def synthesize(self, text: str, speaker: str) -> bytes:
        """16bit・24kHz・モノラルの WAV を返す。"""
        res = _post("https://texttospeech.googleapis.com/v1/text:synthesize", {
            "input": {"text": text},
            "voice": {"languageCode": "ja-JP", "name": self.voices[speaker]},
            "audioConfig": {"audioEncoding": "LINEAR16", "sampleRateHertz": SAMPLE_RATE, "speakingRate": self.rate},
        })
        return base64.b64decode(res["audioContent"])


class GoogleSTT:
    def transcribe(self, wav: bytes) -> str:
        res = _post("https://speech.googleapis.com/v1/speech:recognize", {
            "config": {"encoding": "LINEAR16", "sampleRateHertz": SAMPLE_RATE, "languageCode": "ja-JP",
                       "enableAutomaticPunctuation": True},
            "audio": {"content": base64.b64encode(wav).decode()},
        })
        return "".join(r["alternatives"][0]["transcript"] for r in res.get("results", []))


class WhisperSTT:
    def __init__(self, model: str = "medium"):
        from faster_whisper import WhisperModel  # pip install faster-whisper
        self.model = WhisperModel(model, compute_type="int8")

    def transcribe(self, wav: bytes) -> str:
        segs, _ = self.model.transcribe(io.BytesIO(wav), language="ja", beam_size=5)
        return "".join(s.text for s in segs)


def concat_wavs(parts: list[bytes], gap_sec: float = 0.35) -> bytes:
    """同じ形式の WAV をつなぎ、行の間に短い無音を入れる。"""
    out = io.BytesIO()
    with wave.open(out, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SAMPLE_RATE)
        silence = b"\x00\x00" * int(SAMPLE_RATE * gap_sec)
        for i, p in enumerate(parts):
            with wave.open(io.BytesIO(p)) as r:
                w.writeframes(r.readframes(r.getnframes()))
            if i < len(parts) - 1:
                w.writeframes(silence)
    return out.getvalue()


if __name__ == "__main__" and "--list-voices" in sys.argv:
    req = urllib.request.Request("https://texttospeech.googleapis.com/v1/voices?languageCode=ja-JP", headers=_headers())
    with urllib.request.urlopen(req, timeout=60) as r:
        for v in json.loads(r.read())["voices"]:
            print(v["name"], v.get("ssmlGender", ""))
