# Claude Code → GitHub PR → 自動テストと Codex レビュー

## 自動テスト

`.github/workflows/pr-checks.yml` は main 向け PR の作成（draft を含む）・追加 push・再オープン・Ready への変更で動く。
Linux（Ubuntu 24.04、Python 3.12、Node 22、Playwright 1.56 の Chromium）で次を実行する。

| チェック | 範囲 |
| --- | --- |
| ビルド・構文 | 全7言語を生成し、src/app の JS と生成 HTML、Python の構文を検査 |
| 成果物の一致 | 生成した全7言語 HTML とコミット済み HTML の差分がないこと。更新日を含む sitemap.xml は比較対象外 |
| lyrics_import_e2e | SRT/VTT/JSON/LRC の歌詞と時刻の取り込み |
| text_style_e2e | 行・句の指定、固定した時刻、語の時刻、保存→再読込など既存の回帰テスト |
| media_e2e | 画像の追加・切替・保存→再読込・短い MP4。CI では書き出しの skip も失敗にする |
| video_e2e | 合成クリップの時刻、プレビューと書き出しフレームの比較、再読込、PNG |
| front_e2e | 前景の配置・重なり・透過・クロマキー。同じ画像を異なるキー＋加工で重ねたプレビューと MP4。書き出しの skip も失敗にする |
| chroma_e2e | WebGL と実際に処理した CPU の画像・動画フレーム、色・しきい値・なだらかさ・spill 変更後の加工キャッシュ、キャンバスの再利用 |
| place_e2e | 前景の配置編集：「前」で置く、プレビューの枠をマウスで動かす・大きさ・回転、一覧の時間・不透明度、スポイト、再読み込み |
| place_regression_e2e | 横・縦画面の動き／回転／wipeと採色の一致、通常プレビューでも同じ動画の別時刻を採色、非同期採色の解除、ドラッグ中の保存後もキャンセルを復元 |
| smoke_all | 全860部品とメディアの組み合わせ。problems / page errors があれば終了コード1。slow frames は合否に使わない |

既存の TypeScript / lint 設定はないため、今回は構文検査を基盤にする。型検査やスタイルlintが通ったという意味ではない。
AE/CEP、MCP SDK、加工全般の専用E2E（media_look_e2e）は常時CIには含めない。該当部分を変更したPRでは `CLAUDE.md` の追加コマンドを実行し結果を残す。
書き出しは合成素材による数値検証であり、H.264/AAC の実素材・実機GPU・Safari/Edge・実際の歌唱と歌詞の同期を保証しない。

GitHub Actions は read-only の contents 権限だけを使う。APIキーは不要。PRブランチへの自動修正、承認、マージ、公開は行わない。
チェックが失敗したら同じブランチで修正して push し、新しい SHA の実行が完了するまで確認する。
保護ルールによるマージ必須チェックの設定は、このワークフロー追加とは別の管理者操作。

## ローカル・Codex クラウドで同じ検証をする

Python 3.12 と Node 22 がある Linux 環境で、リポジトリ直下から実行する。
Codex の保存済み環境でも最初に準備が必要（Claude の SessionStart フックは自動実行されない）。

```sh
python3 -m venv /tmp/my-jizura-venv
. /tmp/my-jizura-venv/bin/activate
python3 -m pip install -r dev/requirements.txt
python3 -m playwright install --with-deps chromium
python3 dev/ci.py
```

静的検査だけなら `python3 dev/ci.py --static-only`（Pythonパッケージは不要）。
ビルド後のブラウザ検査だけなら `python3 dev/ci.py --browser-only`。
各テストは一時プロファイル・合成素材を使い、smoke の localhost:8765 サーバーはランナーが起動・終了する。8766/8768/8769 も既存E2Eが使うので、同時実行しない。
生成 HTML の差分が出たら `python3 build.py` の結果を確認してコミットし、最終コミットで再実行する。

## Codex レビュー（公式連携）

テストは GitHub Actions、コードレビューは既存の Codex GitHub 連携が担当する。保存済み Codex 環境を用意しただけでは PR テストは起動しない。

調査時（2026-10-05、main `68ebeeb`）は、リポジトリ内にワークフロー・AGENTS.md・`.agents/skills` はなかった。Actions の履歴9件はすべて Pages 公開で、PRテストはなかった。
[PR #12 の記録](https://github.com/hey-taka88/my-jizura/pull/12#issuecomment-5990203077)では Codex が `a695cf0` を「Draft marked ready」でレビュー完了している。
ただし過去の実行だけでは、現在の対象範囲（全PR／個人設定）や追加push時の再レビューは確認できない。
main のブランチ情報は `protected: false`、required status checks は空だった。CIやレビュー完了をマージ条件として強制する設定は今回変更していない。

[OpenAI公式手順](https://developers.openai.com/codex/integrations/github/)に従い、
[Codex settings](https://app.chatgpt.com/settings/code-review) でこのリポジトリの Automatic review、Personal preferences、Review trigger を所有者が確認する。
必要な時点でレビューが動かなければ、PRに `@codex review` とコメントして依頼できる。
Readyへの変更を契機とする設定では、draftの作成だけでは自動レビューは起動しない。draftでも手動の `@codex review` は依頼できる。
`AGENTS.md` の Code Review Rules はレビュー観点を伝えるもので、自動レビューを有効化する設定ではない。
APIキーを使う別のCodex Actionは追加しない。新たなアプリ・権限・課金の導入が必要なら事前に所有者へ相談する。

## 人が確認すること

PR本文には検証したSHAと passed / failed / not run、および変更に合う手動確認手順を記載する。
MV制作に影響する変更では、採用プロジェクトのコピーで次を確認する。

1. 固定したカットの隣を編集し、固定カットの時刻・動き・色を見比べる。
2. 歌詞の誤字や句読点だけを直し、開始・終了・句境界が意図せず動かないか確認する。
3. 保存→再読込で素材と採用した構成が戻ることを確認する。
4. 対象区間を実機でプレビュー・書き出しし、見た目・GPUの滑らかさ・動画と音声・歌詞と歌唱の同期を目と耳で確認する。

これらの全パターンを今回のCIが網羅したという意味ではない。Codexのレビュー結果・CI・人の確認をそれぞれ記録して判断する。
