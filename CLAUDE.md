# 毎朝5分ラジオ（maiasa-radio）

自分専用の、AI・経済・世界のニュースを学ぶラジオ。平日と土曜の **朝5時半まで** に新しい回を公開する。
ユーザーへの説明・報告は日本語で、専門用語を避けて分かりやすく書く。

## 決まっていること

| 項目 | 内容 |
|---|---|
| 公開先 | `config.json` の `artifact_url`（claude.ai の非公開ページ。ページの元は `web/radio.html`） |
| アレクサ | `config.json` の `feed_base_url`（GitHub Pages の `gh-pages` ブランチ。アレクサのフラッシュニュース用。ここの音声は誰でも取得できる） |
| 番組表 | `config.json` の `schedule`。月・木＝AI、火・金＝経済、水＝世界特集、土＝今週のまとめ、日＝お休み。AI・経済の日は最後に「世界の1分」 |
| 話し手 | ハル（解説・男性・Charon）、ソラ（聞き役・女性・Leda）。声は `config.json` の `voices` |
| 長さ | 台本 1,800〜2,000字（話す速さ1.25倍で約5分。実測で1分あたり約370字）。1行は60字以内。話す速さは `config.json` の `speaking_rate`（2026-11-18 ユーザーの希望で1.25倍） |
| 話題のタグ | `config.json` の `tags` から選ぶ（評価の集計に使うので、勝手に増やさない） |
| APIキー | 作業環境のネットワークシークレット（`X-Goog-Api-Key`）。コード・リポジトリ・チャットにキーを書かない |
| git | 毎朝の成果物（`episodes/`、`site/data/`、`reading_dict.json`、`reports/`）だけは `main` に直接コミットしてよい（2026-11-18 ユーザー承認）。仕組みの変更はブランチで行い、ユーザーの承認を得てから `main` に反映する |

## 毎朝の手順（定期実行）

### 0. 準備
1. `pip install --use-pep517 -r requirements.txt`（`--use-pep517` を付けないと、読みの辞書部品 unidic-lite のインストールに失敗することがある）
2. 今日の日付と曜日を日本時間で確かめる：`TZ=Asia/Tokyo date '+%F %a'`
3. `config.json` の `schedule`（月曜が先頭）で今日のテーマを確かめる。**日曜は何もせず終了**する。
4. `site/data/index.json` に今日の回が「公開OK」で載っていれば、何もせず終了する（二重に作らない）。

### 1. 好みを読む
- ArtifactData で `artifact_url` のコレクション `feedback` を `list` し、`out_dir: build/feedback` に保存する。
- `python -m pipeline.prefs build/feedback` で好みを計算する（`prefer`／`avoid`／`deep`／`hard`）。
- 評価がまだなければ、そのまま進める。

### 2. ニュースを集める
- WebSearch で、前回の放送以降（目安：直近24〜72時間）のニュースを探す。
- 話題の数
  - AI・経済の日：3話題＋「世界の1分」1話題
  - 世界特集（水）：3話題
  - 今週のまとめ（土）：今週の回（`site/data/episodes/` の月〜金）から、評価が高い話題・「もっと深く」が押された話題を2〜3つ選んで深掘りし、続報があれば加える
- **事実は、一次情報か信頼できる報道で確かめる**（各社の公式発表、Reuters、AP、Bloomberg、NHK、日経、TechCrunch など）。まとめサイトにしか出ていない話は使わない。
  - 教訓（2026-11-05）：まとめサイトに出ていた「Meta の Conductor 買収」「AIが脆弱性948件を発見」は、元の報道を確認できなかった。
- 好みの反映：`prefer` の話題を優先し、`avoid` は短めにする。ただし2〜3割は、好みに関係なく重要なニュースを入れる（探索枠）。
- 話題ごとに出典のタイトルとURLを控える。

### 3. 台本を書く（`episodes/<日付>.json`）
- 形式は `episodes/2026-11-05.json` を手本にする。
  - `date`、`theme`（ai／eco／world／sum）、`title`（例：「11月19日（木） AIの回」）、`subtitle`（例：「＋世界の1分ニュース」）
  - `chapters`：`op`（オープニング）→ 話題（`t1`〜`t3`、世界の1分は `w`）→ `ed`（エンディング）。話題のコーナーには `label`・`tags`・`slide`・`sources` を付ける。
  - `slide` の種類：`agenda`（きょうの内容）、`points`（要点3つ）、`big`（大きな数字1つ。`meter` は0〜100の任意）、`boxes`（3つの箱。色は `dem`／`rep`、ほかは省略）、`ending`（クイズと次回の案内）
  - `lines`：`chapter`（コーナーのkey）、`speaker`（`hal` か `sora`）、`text`
  - `quiz`：`q`、`options`（3つ）、`answer`（正解の番号、0始まり）、`explain`
- 書き方
  - 冒頭はソラ：「おはようございます。○月○日、○曜日の『毎朝5分ラジオ』です。今日は○○の回です。」
  - ハルが解説し、ソラが聞き手の素朴な疑問で話を進める。
  - 確かめきれないことは「〜と報じられています」「〜かもしれません」と言い、推測を事実のように言わない。
  - 数字には単位を付け、外国の通貨は日本円の目安も添える。
  - 日付は「今月12日」ではなく「11月12日」のように月から言う（「今月12日」は文字起こしが「今月中に」と聞き間違え、公開保留になった。2026-11-21）。
  - エンディングはクイズと次回の案内（土曜は「次は月曜、AIの回です」）。

### 4. 読みを決める
1. `python -m pipeline.gate episodes/<日付>.json --prepare-only`
2. 止まった言葉を解決する。
   - 英字・固有名詞：`reading_dict.json` に追加する（`forms` に書き方、`reading` にカタカナ）。
   - 読み分けが必要な言葉、数字＋助数詞：その行に `"yomi": {"表記": "よみ"}` を付ける（文脈から読みを決める）。
3. 終了コード 0 になるまで繰り返す。

### 5. 公開前チェック（約2分）
`python -m pipeline.gate episodes/<日付>.json`
- **0（公開OK）**：6へ。
- 不合格の行は自動で作り直す（最大3回。最後の1回は話す速さを `retry_slow_rate`＝1.0倍に落とす）。億・兆の付く金額は、文字起こしで億・兆が落ちても数字と単位で確かめる。
- **2（公開保留）**：`build/<日付>/report.json` の `failed` の行を見る。
  - 言い回しを変えれば直りそうなら（聞き取りにくい言葉の言い換えなど）、台本を直して4からやり直す（1回まで）。
  - 直らなければ `python -m pipeline.site <日付> --held "理由"` で保留として載せ、7・8を行う。最後の報告に、不合格の行と確認用の音声（`build/<日付>/review.wav`、`line-XX.wav`）のことを書く。

### 6. ページ用のデータを作る
`python -m pipeline.site <日付>` を実行し、最後の行に出る JSON（`files` の指定）を控える。

### 7. ページを更新する
1. Artifact で `action: "read"`、`url: <artifact_url>` を実行し、公開中のページを読む。読まずに公開すると拒否される。
2. Artifact で公開する：`file_path: web/radio.html`、`url: <artifact_url>`、`files: <6 の JSON>`。
   - `capabilities` と `icon` は渡さない（保存済みの設定を引き継ぐ）。
3. アレクサ用のフィードを更新する：`python -m pipeline.feed <日付> --push`
   - 公開保留の日は `python -m pipeline.feed <日付> --held --push`（アレクサが「今日はお休み」と読み上げる）。
   - フィードは `config.json` の `feed_base_url`（GitHub Pages）に置かれ、アレクサのフラッシュニュースが15分ごとに取りに来る。5時半に間に合うよう、この手順までを早めに終える。

### 8. 保存する
1. `cp build/<日付>/report.json reports/<日付>.json`（保留でも行う）
2. `git add episodes/<日付>.json reading_dict.json site/data reports/<日付>.json`
3. `git commit -m "<日付> の回"`
4. `git push origin main`

### 9. 報告する（最後のメッセージ）
次のことを短く書く：公開OK／保留、取り上げた話題、公開前チェックの結果（作り直し・聞き直しの行数）、新しく読み辞書に加えた言葉。

## 手で動かすとき
- テスト：`python -m unittest discover -s tests -t .`
- 仕組みの説明は `README.md`。
