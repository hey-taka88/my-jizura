# エージェントから JIZURA を動かす（MCP サーバーとコマンド）

Claude（Claude Code・Claude Desktop）や Codex に、こんなふうに頼めるようにするためのものです。

> 「`mv` フォルダの曲と Suno の歌詞 JSON と画像で、しっとり系の 16:9 と 9:16 を書き出して。途中でフレームを見て、文字が読みにくければ直して」

アプリはブラウザの中で全部動くので、**見えないブラウザでこのフォークの `index.html` を開いて、パネルと同じ関数を呼びます**。
見た目や書き出しの結果は、ブラウザで手で操作したときと同じです。

| ファイル | 役目 |
|---|---|
| `tools/jizura_driver.py` | 土台。ページを開いて操作する関数の集まり（CLI と MCP サーバーが使う） |
| `tools/jizura_cli.py` | コマンド。1 回の実行で「読み込み → 見た目 → 書き出し」まで。Claude Code なら MCP なしでもこれを呼べる |
| `tools/jizura_mcp.py` | MCP サーバー。エージェントが 1 手ずつ操作し、プレビューの画像を見て直せる |

## 準備（自分の PC で 1 回だけ）

1. Python 3.10 以上と git を入れる
2. このリポジトリを取ってくる：`git clone https://github.com/hey-taka88/my-jizura.git`
3. 必要なものを入れる：
   ```
   cd my-jizura
   pip install -r tools/requirements.txt
   python3 -m playwright install chromium
   ```
4. **Google Chrome か Microsoft Edge が入っていること**（入っていれば自動で使います）。
   AI 動画の多くは H.264 の MP4 で、Playwright の Chromium だけでは読めません。書き出しの MP4 も Chrome なら H.264、Chromium だと VP9 になります。
5. 作業フォルダを作って、曲・歌詞・画像・動画を入れる（例 `~/mv`）。ツールはこのフォルダの中しか読み書きしません。

`index.html` はビルド済みのものがリポジトリに入っているので、`python3 build.py` は `src/` を変えたときだけで大丈夫です。

## MCP サーバーをつなぐ

パスは自分の場所に置き換えてください。Windows では `python3` を `python` か `py` に変えます。

**Claude Code**
```
claude mcp add jizura -- python3 /path/to/my-jizura/tools/jizura_mcp.py --workdir /path/to/mv
```
長い曲の書き出しで時間切れになるときは、`MCP_TOOL_TIMEOUT=1800000 claude` のように待ち時間（ミリ秒）を延ばして起動します。

**Claude Desktop**（設定 → 開発者 → 構成を編集、または `claude_desktop_config.json` を直接開く）
```json
{
  "mcpServers": {
    "jizura": {
      "command": "python3",
      "args": ["/path/to/my-jizura/tools/jizura_mcp.py", "--workdir", "/path/to/mv"]
    }
  }
}
```

**Codex CLI**（`~/.codex/config.toml`）
```toml
[mcp_servers.jizura]
command = "python3"
args = ["/path/to/my-jizura/tools/jizura_mcp.py", "--workdir", "/path/to/mv"]
tool_timeout_sec = 1800
```

設定（どれも省略可）：
- `--workdir`（または環境変数 `JIZURA_WORKDIR`）：読み書きしてよいフォルダ。省略するとサーバーを起動したフォルダ
- `--browser`（`JIZURA_BROWSER`）：`auto`（Chrome → Edge → Chromium の順）・`chrome`・`msedge`・`chromium`
- `--app`（`JIZURA_APP`）：別の `index.html` を使うとき

## ツール

| ツール | すること |
|---|---|
| `list_files` | 作業フォルダの歌詞・曲・画像・動画・プロジェクトの一覧 |
| `status` | 使っているブラウザと、H.264 を読み書きできるか |
| `options` | テーマ・スタイル・雰囲気・画面比など、選べる値の一覧 |
| `new_project` / `open_project` / `save_project` | プロジェクトを新しく作る・開く（`.jizura.json`）・保存する。保存は `{requested, saved, collision}` を返すので、次に開くときは **`saved`** を使う。`replace=true` で、このサーバーが今回書いたファイルなら同じ名前に上書き。開いたときに読み込まれていない画像・動画は `missing` に出る |
| `add_timed_media` / `remove_timed_media` | 曲の時刻で画像・動画を置く（例：曲全体に 1 本の背景動画）。行ごとの自動の画像より優先、行ごとに選んだ画像よりは下。動画は曲の時計で流れ続け、行の切り替えで頭に戻らない。`track='front'` で**歌詞の上（前景）**に置く（ロゴ・立ち絵・透過 PNG・枠）：前景は重ねてよく（あとから始まるものが上）、終わりを指定しなければ曲の最後まで、それぞれがフェードで出入りする。`x` / `y`（画面の中心からのずれ。±0.5 で端）・`size`（画面の幅に対する幅）・`rot`（度）のどれかを渡すと、画面いっぱいではなくその位置・大きさで置く（背景でも可）。`opacity`、`enter` / `exit` / `hold` も |
| `set_lyrics` | 歌詞を入れる（LRC・SRT・VTT・Whisper / Suno の JSON は時刻付き、テキストは 1 行 1 フレーズ）。Suno の `aligned_words`・WhisperX などの単語ごとの時刻と拡張 LRC の `<mm:ss.xx>` は**語の時刻**として残り、行の中の句（カット）が、その語を歌う時刻で切り替わる。`wordTimed` に語の時刻を持つ行の数が返る |
| `load_song` | 曲を読み込む（長さとテンポを解析） |
| `add_media` / `remove_media` | 画像・動画を足す（フォルダなら名前順）・外す |
| `set_line_media` | 行ごとの画像（名前・番号・`none`＝画像なし・`auto`＝順番） |
| `set_look` | 見た目：テーマのおまかせ、案の番号（同じ番号なら同じ見た目）、スタイル・雰囲気の固定 |
| `get_line` / `set_line_style` | 1 行（またはその中の 1 カット）の見た目を固定：配置（中央・縦書き・画面突き抜け…）・登場／退場／保持の動き・カメラ・背景グラフィック・装飾（`[]` でなし）・カット数と 2 つ目以降の句の開始時刻・位置（x / y）・大きさ・文字色・固定（`lock`）。`auto` で自動に戻す。`get_line` で実際に使われた部品が分かる。`get_line` は語の時刻（`words`）、その行でいちばん低い合わせの確かさ（`confidence`、Suno の `p_align` など）、句の開始時刻の決まり方（`cutTimes`：`by hand` 手で指定 ＞ `locked` 固定したときの時刻 ＞ `words` 語の時刻 ＞ `auto` 文字数で配分）も返す。語ごとに `p`（確かさ）と `used`（句の切り替えに使ったか）、カットごとに `sung`（その句を歌う時刻）が付く |
| `set_text_options` | 長い間奏に曲名を出すか（曲名はプロジェクトに残る） |
| `get_motion_plan` | 曲の時刻の範囲で、アプリが実際に作ったカットを読む（読むだけで何も変えない）：行（1 始まり）とその中のカット番号・時刻・文字・recap・配置・登場／退場／保持・加工・カメラ・切り替え・背景グラフィック・装飾・params・配色の番号・登場／退場の長さ・seed・固定されているか、と範囲で使われた部品の一覧（`inventory`）。候補（`set_look` の variation / seed）を見比べる、固定した範囲が変わっていないか確かめる、に使う |
| `lock_motion_palette` | 採用した範囲を固定：範囲にかかる歌詞の行を、今のカット・動き・装飾・**句の開始時刻ごと**固定する（他の行に `set_look` や `set_line_style` をしても変わらない）。`lock=false` で外す（手で決めた句の時刻と、固定のあとに直した時刻は残る）。固定した行に `set_line_style` で位置・大きさ・文字色を変えても、カットと時刻はそのまま。`scheme` で範囲のカットの配色を固定。色（`bg_color` / `text_color` / `sub_color` / `accent_color` / `ghost_a` / `ghost_b`）と `chroma` は**プロジェクト全体**に効く（「配色」パネルと同じ）。基本色を渡すと `scheme` は 0。1 行だけの文字色は `set_line_style(color=…)` |
| `set_range_style` | 曲の秒の範囲の**見せ方の強さ**：`quiet`（1 行 1 カット・中央に大きく・ぼかして出入り・ゆっくり呼吸。サビのあいだの休み）、`calm`（JIZURA の配置とカットのまま、ぼかして出入り・ゆっくり漂う）、`normal`（自動に戻す）。`quiet` と `calm` は装飾・強いカメラ・画面効果（揺れ・グリッチ・フラッシュなど）・カットのつなぎ効果なし。`layout` / `enter` / `exit` / `hold` / `cam` で範囲全体の部品を 1 つ上書き、`size` で大きさ。範囲の中の固定した行は、強さを当ててから固定し直す。JIZURA は直前に使った部品を避けて選ぶので**範囲の外の行も変わることがある**（`othersChanged` に出る）。残したい範囲は先に `lock_motion_palette` で固定しておく |
| `set_word_times` | 今の歌詞はそのままで、語の時刻だけを足す（Suno の `aligned_words`・WhisperX の単語・拡張 LRC・words 付きの `lines` の JSON。例：`timing_master.json`）。行は同じ文字で時刻のいちばん近いものを使う。確かさ 0.1 未満の語と、行の外にある語の時刻は使わない。`without`（語の時刻がない行）・`unmatched`（どの行とも文字が合わない語の時刻）・`weak`（使わなかった語がある行）・`off`（歌う時刻に 0.3 秒より合わせきれなかったカット。行の表示が歌より短いときなど）を返す。ファイルの時刻を直して呼び直せばそのまま反映される |
| `relink_media` | 開いたプロジェクトで読み込まれていない素材（`missing`）を、フォルダから中身で探して戻す（名前が変わっていても見つかる） |
| `set_media_options` | 画像の並び・動き（寄る・流す・漂う・拍で脈打つ…）・つなぎ（クロスフェード・切り替え効果）・登場退場・加工（モノクロ・2 色トーン…）・暗さ・文字の下の暗幕、短い動画の伸ばし方（ループ・往復・止める・拍で頭出し） |
| `media_omakase` | 「メディアのおまかせ」：動き・つなぎ・登場・加工・暗さ・並びをまとめて決める（呼ぶたびに別の案） |
| `set_output` | 画面比・解像度・fps・画質 |
| `get_plan` | 各行の時刻・歌詞・表示される画像、見た目、曲の情報 |
| `preview` | その時刻のフレームを画像で返す（モデルが見て判断できる） |
| `export_mp4` | MP4 を作業フォルダに書き出す（一部の秒だけも可）。保存と同じく `saved` と `replace`。長さは予定（`duration`）・書いたフレーム数と映像の長さ（`frames` / `videoDuration`）・音声の長さ（`audioDuration`）を別々に返す |

| `log_note` / `run_info` / `start_run` | 制作の記録（下）にメモを残す・記録の場所と要約を見る・曲ごとに記録を分ける |

### 制作の記録

MCP サーバーは、作業フォルダの `jizura_runs/<日時>_<名前>/` に、1 回の制作で何が起きたかを自動で残します（`--no-record` か `JIZURA_RECORD=0` で止められます）。

| ファイル | 中身 |
|---|---|
| `report.md` | 日本語のまとめ：メモ（近い時刻のプレビュー画像つき）、書き出したファイル、段階ごとの時間、ツールが断ったこと、読んだファイル |
| `run.json` | まとめ（機械向け）：アプリの版と git のコミット、ブラウザと H.264 対応、時間（全体／ツールの中／ツールとツールのあいだ）、読んだ・書いたファイルの sha256、プロジェクトの状態の移り変わり、メモ、エラー |
| `calls.jsonl` | ツールの呼び出し 1 回ごとに 1 行：引数、結果の要約、かかった時間、その前の待ち時間、そのあとのプロジェクトの状態（ハッシュ） |
| `previews/` | プレビューで返した画像すべて（`<呼び出し>_<番号>_<秒>s.png`） |
| `projects/` | プレビュー・書き出し・保存に使ったプロジェクトの JSON（状態ごとに 1 つ） |

- エージェントには「気づいたこと・困ったこと・手で直したことは `log_note` に、曲の時刻か行の番号を付けて残して」と頼むと、あとで直す材料になります（`kind`：`issue` 問題・`workaround` 手で回避・`decision` 判断・`note` メモ）
- 曲を変えるときは `start_run`（記録のフォルダが分かれる）
- **改善を頼むとき**は、そのフォルダ（`jizura_runs/…`）をまるごと zip にして渡すと、何が起きたかをそのまま追えます。書き出した動画そのものは入っていないので、必要なら一緒に

### 安全のしくみ

- 読み書きは作業フォルダの中だけ。外のパス（`../` など）はエラーになります（記録も作業フォルダの `jizura_runs/` に書きます）
- 前からあるファイルは上書きしません（`mv.mp4` があれば `mv-2.mp4` に書き、返り値の `saved` で知らせます）。`replace=true` で上書きできるのは、このサーバーが今回書いたファイルだけです
- ページが外に出られるのは、このアプリと Google Fonts（文字の形を取ってくる）だけです
- 毎回まっさらなブラウザで開きます。続きはプロジェクトを保存して `open_project` で開き直します（画像は `add_media` で入れ直すと、中身で見分けて行ごとの指定が戻ります）

### 頼み方の例

- 「`list_files` で中身を見て、`song.mp3` と `suno.json` と `pics` フォルダで 16:9 を作って。テーマはバラード」
- 「4 枚くらいプレビューを見せて。文字が写真に埋もれていたら、文字の下の暗幕を付けるか、暗さを上げて」
- 「写真の切り替えをもっと派手に。いろいろな切り替え効果で、写真はスタイルの色に寄せて」
- 「3 行目は `sunset.jpg`、サビ前の行は画像なしにして」
- 「同じ設定で 9:16 も書き出して。ファイル名は `mv_vertical.mp4`」
- 「`bg.mp4` を曲全体の背景にして（行ごとに頭から再生しないで）。サビの 1 行目だけ `sunset.jpg` に」
- 「サビの 1 行目は画面中央に大きく、装飾なしで固定。2 行目は後半の句を 1.6 秒後に切り替えて。指先を避けたいので 5 行目は上の方に」
- 「間奏には曲名を出さないで」

## コマンドで使う（MCP なし）

```
# 書き出し（画面比を 2 つ指定すると、mv_16x9.mp4 と mv_9x16.mp4 の 2 本）
python3 tools/jizura_cli.py render --lyrics suno.json --song song.mp3 --media pics/ \
    --theme ballad --aspect 16:9 --aspect 9:16 --out out/mv.mp4 --save-project out/mv.jizura.json

# 確認用のフレーム（歌詞の行から均等に 6 枚）
python3 tools/jizura_cli.py preview --lyrics suno.json --media pics/ --theme ballad --count 6 --out-dir shots/

# 行・時刻・画像の一覧（JSON）／選べる値とブラウザの対応状況
python3 tools/jizura_cli.py plan --project out/mv.jizura.json --media pics/
python3 tools/jizura_cli.py info
```

ほかの指定：`--line-style 3:layout=center,y=-0.2,size=1.4,color=#ffffff,decor=none,lock=1`（行の見た目を固定。`2:cut_times=1.6` で 2 つ目の句を 1.6 秒後に、`4.2:layout=vcols` で 4 行目の 2 カット目だけ）、`--word-times timing_master.json`（歌詞はそのままで語の時刻だけを足す）、`--range-style 33.3-42.6=quiet`（その秒の範囲の見せ方の強さ。`calm` / `normal` も。何度でも）、`--no-interlude-title`、`--relink 素材フォルダ`（`--project` の素材を戻す）、`--line-media 3=sunset.jpg`（何度でも）、`--timed-media bg.mp4@0-`（曲全体に背景動画。`city.jpg@30-45` のように区間も可）、`--front-media logo.png@0-:x=0.4,y=-0.4,size=0.15`（歌詞の上に重ねる。`rot=`・`opacity=` も。何度でも）、`--dim 0.4`、`--hold pan`、`--trans mix`、`--enter slide`、`--treat duotone`、`--scrim always`、`--media-omakase`、`--extend pingpong`、`--variation 2`、`--style noir`、
`--res 720`、`--fps 30`、`--range 30-45`（その秒だけ）、`--no-audio`、`--force`（上書き）。一覧は `python3 tools/jizura_cli.py render -h`。

## うまくいかないとき

- **動画が「再生できませんでした」になる**：H.264 なら Chrome か Edge を入れる（`status` で `h264Decode` が `true` になるか確認）。H.265（HEVC）は Chrome でも読めないことがあるので、H.264 か WebM に変換する
- **書き出した MP4 が VP9 になる**：Chrome が見つかっていません。`--browser chrome` を付けると、見つからないときにエラーで分かります
- **時間がかかる**：見えないブラウザは GPU を使わないことが多く、1080p だと曲の長さの数倍かかることがあります。まず `--res 720` や `--range` で短く試すのがおすすめ
- **文字の形が違う**：Google Fonts に届かない環境では、PC に入っている文字で描かれます

## 確認（開発者向け）

`python3 dev/mcp_e2e.py`：作業フォルダに曲（WAV）・Suno 形式の歌詞・画像 3 枚を作り、本物の MCP クライアントからサーバーにつないで全ツールを通しで確認します（mcp 1.x と 2.x の両方で確認済み）。
