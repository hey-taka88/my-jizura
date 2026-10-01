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
| `new_project` / `open_project` / `save_project` | プロジェクトを新しく作る・開く（`.jizura.json`）・保存する |
| `set_lyrics` | 歌詞を入れる（LRC・SRT・VTT・Whisper / Suno の JSON は時刻付き、テキストは 1 行 1 フレーズ） |
| `load_song` | 曲を読み込む（長さとテンポを解析） |
| `add_media` / `remove_media` | 画像・動画を足す（フォルダなら名前順）・外す |
| `set_line_media` | 行ごとの画像（名前・番号・`none`＝画像なし・`auto`＝順番） |
| `set_look` | 見た目：テーマのおまかせ、案の番号（同じ番号なら同じ見た目）、スタイル・雰囲気の固定 |
| `set_media_options` | 画像の並び・動き（寄る・流す・漂う・拍で脈打つ…）・つなぎ（クロスフェード・切り替え効果）・登場退場・加工（モノクロ・2 色トーン…）・暗さ・文字の下の暗幕、短い動画の伸ばし方（ループ・往復・止める・拍で頭出し） |
| `media_omakase` | 「メディアのおまかせ」：動き・つなぎ・登場・加工・暗さ・並びをまとめて決める（呼ぶたびに別の案） |
| `set_output` | 画面比・解像度・fps・画質 |
| `get_plan` | 各行の時刻・歌詞・表示される画像、見た目、曲の情報 |
| `preview` | その時刻のフレームを画像で返す（モデルが見て判断できる） |
| `export_mp4` | MP4 を作業フォルダに書き出す（一部の秒だけも可） |

### 安全のしくみ

- 読み書きは作業フォルダの中だけ。外のパス（`../` など）はエラーになります
- 既存のファイルは上書きしません（`mv.mp4` があれば `mv-2.mp4` に書きます）
- ページが外に出られるのは、このアプリと Google Fonts（文字の形を取ってくる）だけです
- 毎回まっさらなブラウザで開きます。続きはプロジェクトを保存して `open_project` で開き直します（画像は `add_media` で入れ直すと、中身で見分けて行ごとの指定が戻ります）

### 頼み方の例

- 「`list_files` で中身を見て、`song.mp3` と `suno.json` と `pics` フォルダで 16:9 を作って。テーマはバラード」
- 「4 枚くらいプレビューを見せて。文字が写真に埋もれていたら、文字の下の暗幕を付けるか、暗さを上げて」
- 「写真の切り替えをもっと派手に。いろいろな切り替え効果で、写真はスタイルの色に寄せて」
- 「3 行目は `sunset.jpg`、サビ前の行は画像なしにして」
- 「同じ設定で 9:16 も書き出して。ファイル名は `mv_vertical.mp4`」

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

ほかの指定：`--line-media 3=sunset.jpg`（何度でも）、`--dim 0.4`、`--hold pan`、`--trans mix`、`--enter slide`、`--treat duotone`、`--scrim always`、`--media-omakase`、`--extend pingpong`、`--variation 2`、`--style noir`、
`--res 720`、`--fps 30`、`--range 30-45`（その秒だけ）、`--no-audio`、`--force`（上書き）。一覧は `python3 tools/jizura_cli.py render -h`。

## うまくいかないとき

- **動画が「再生できませんでした」になる**：H.264 なら Chrome か Edge を入れる（`status` で `h264Decode` が `true` になるか確認）。H.265（HEVC）は Chrome でも読めないことがあるので、H.264 か WebM に変換する
- **書き出した MP4 が VP9 になる**：Chrome が見つかっていません。`--browser chrome` を付けると、見つからないときにエラーで分かります
- **時間がかかる**：見えないブラウザは GPU を使わないことが多く、1080p だと曲の長さの数倍かかることがあります。まず `--res 720` や `--range` で短く試すのがおすすめ
- **文字の形が違う**：Google Fonts に届かない環境では、PC に入っている文字で描かれます

## 確認（開発者向け）

`python3 dev/mcp_e2e.py`：作業フォルダに曲（WAV）・Suno 形式の歌詞・画像 3 枚を作り、本物の MCP クライアントからサーバーにつないで全ツールを通しで確認します（mcp 1.x と 2.x の両方で確認済み）。
