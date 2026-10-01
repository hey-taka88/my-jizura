# CLAUDE.md — my-jizura での作業ルール

このリポジトリは [852wa/JIZURA](https://github.com/852wa/JIZURA)（文字PV自動構成ツール、MIT）の**自分用フォーク**です。
目的は「文字PVに画像・動画（メディアレイヤー）を入れられるようにする」こと。計画は `docs/PLAN.md`、アイデアは `docs/IDEAS.md`。

## まず読むもの

1. `docs/PLAN.md` §1（今の仕組み）と §2（目標設計）— 全タスクの前提
2. `docs/EXPRESSION_PACKS.md` — 描画部品の掟（決定論・性能・ゴーストパス）。メディア描画にもそのまま適用
3. 触るファイルの近くのコード。特に `src/09_render.js` の `frame()`、`src/08_planner.js` の `J.defaultProject` / `J.plan` / `makeCut`、`src/12_ui.js` の `S` / `replan()` / `mergeProject()` / `boot()`

## リポジトリの構造

```
src/            ブラウザ版のエンジン・部品・UI。ビルドは sorted(glob('src/*.js')) の文字列順に連結
  01_util … 10_audio   コア（本家）        11p_*.js 表現パック（本家）   11q_sets.js 部品セットの切替
  12_ui.js             エディタ UI（本家）
  08m_*.js             ★フォーク：メディアレイヤーのエンジン（09_render より前に読み込まれる）
  11z_*.js             ★フォーク：メディアレイヤーの UI（12_ui より前に読み込まれる）
app/body.html, app/style.css   UI の HTML/CSS（本家）。app/english.py, app/i18n*.py 各言語版
vendor/         mp4-muxer（同梱）
ae/, cep/       After Effects パネル（本家）。メディア対応は Phase 4 の任意
dev/, tools/    テスト・チェックツール
index.html, en/, ko/, … ビルド成果物（**手で編集しない**。python3 build.py で生成）
docs/PLAN.md, docs/IDEAS.md, CHANGELOG.md
```

## コマンド

```
python3 build.py                                  # 必須：src/app/vendor → index.html + 各言語版（成果物もコミットする。GitHub Pages が index.html を配信）
python3 tools/check_page_js.py index.html         # ビルド後ページの構文チェック（node が必要）
node -e "new Function(require('fs').readFileSync('src/08m_media_store.js','utf8'))"   # 単ファイルの構文チェック
python3 dev/build_test.py all --all-packs         # テスト用バンドル dev/www/t_all.html
(cd dev/www && python3 -m http.server 8765 &)     # テストページの配信（playwright 系ツールが使う）
python3 dev/smoke_all.py t_all                    # 全部品を多数の組み合わせで描画。problems 0 と page errors [] が合格
python3 dev/cost_scan.py t_all 45                 # 45ms を超えるフレームの一覧
python3 dev/media_e2e.py [--shots out/media]      # ビルド済みの index.html で画像レイヤーを通しで確認（画像の追加 → 行ごとの切り替え → 再読み込み → 書き出し）。先に python3 build.py
node tools/export_ae_data.js && python3 build_ae.py   # AE パネルを触ったときだけ
```

`dev/www/`・`dev/node_modules/`・`out/`・`__pycache__/` はコミットしない（`.gitignore` 済み）。

### テスト環境の用意

- **Claude Code on the web**：SessionStart フック（`.claude/hooks/session-start.sh`）が `dev/requirements.txt` と `dev/` の npm パッケージを自動で入れる。`playwright install` は実行しない（コンテナに Chromium build 1194 が入っていて、`dev/requirements.txt` の playwright はそれに合わせて 1.56.0 に固定してある）。
- **自分の PC**：`pip install -r dev/requirements.txt && python3 -m playwright install chromium`、AE パネルのテストをするなら `(cd dev && npm install)`。
- **ベースライン（2026-10-01、Phase 1 後）**：`dev/smoke_all.py t_all` は 860 部品＋画像付きの組み合わせで problems 0、page errors []。`dev/media_e2e.py` は全項目 ok。`node dev/ae_test.js` は problems 0。smoke の「slow frames」は GPU のないクラウドのコンテナで 250 前後出るのが普通なので、合否には使わない（増え方が大きいときだけ `dev/cost_scan.py` で調べる）。

## 守ること（本家の掟 + フォークの掟）

- **本家ファイルへの変更は最小限**：新しい機能は `src/08m_*.js` / `src/11z_*.js` に置き、本家ファイル（`08_planner.js`, `09_render.js`, `11_export.js`, `12_ui.js`, `app/body.html`）には `if (J.media) …` でガードした**呼び出し 1 行**だけを足す。upstream を `git merge upstream/main` で取り込み続けるため。
- **決定論**：同じ project からは同じ plan と同じフレームが出る。描画中の `Math.random()` 禁止。乱数は `plan()` 側の `rng` か `J.r()` ハッシュ。
- **性能**：1 描画 ≈ 2ms（1080p）。全画面 `getImageData` 禁止（縮小キャンバスなら可）。毎フレームの canvas / ImageBitmap 生成禁止（キャッシュ）。video 要素は同時 2 本まで。
- **プロジェクト JSON は信用しない**：`mergeProject()` → `J.media.normalize()` で全フィールドを検証・clamp。id は `/^[\w-]{1,32}$/`、色は `#rrggbb`、文字列は長さ制限。素材の実体（バイト列）は JSON に入れない（IndexedDB `files` の `media:<id>`）。
- **既存の歌詞側の挙動を変えない**：`plan.cuts` の中身・順序・シード消費を変えない（既存プロジェクトの見た目が変わる）。抽選を足すときは別の `rng` ストリーム（`J.rng(J.h(seed, 'media'))`）。
- **例外を投げない**：`bb === null`、素材未読み込み、動画の seek 失敗をガードして黒／スキップで続行。`console.warn` に残す。
- **ゴーストパス**：`env.pass !== 'main'` のときにメディアを描かない。
- **透過 PNG の前景／後景分割**（`opt.layer`）と **keyBg（グリーン／ブラックバック）** の両方で正しく動くこと（keyBg 中はメディアを描かない）。
- **UI 文字列は日本語**（本家に合わせる）。英語版は `app/english.py` の対応表に足す。他言語版が `tools/check_i18n.py` で警告しても、自分用なので日本語のままで可。
- **CHANGELOG.md** の先頭「フォーク（my-jizura）」節に書く。本家の節は触らない。`VERSION` は本家のまま（フォーク版は `VERSION` に `+media.N` を付ける案は Phase 4 で決める）。
- **ビルド成果物（index.html 等）もコミットする**（本家と同じ運用。Pages が直接配信）。ただし PR の diff を読むときは `src/` `app/` だけを見る。

## PR の完了条件（毎回）

1. `python3 build.py` が成功し、`python3 tools/check_page_js.py index.html` が通る
2. 新規・変更した `src/*.js` の `node -e "new Function(...)"` が通る
3. できれば `dev/smoke_all.py t_all` が problems: 0（環境に playwright があるとき）
4. 手動確認の手順を PR 本文に書く（例：「写真 3 枚を落とす → 一括配置 → 再生 → MP4 書き出し → 3 枚が行ごとに切り替わる」）
5. `docs/PLAN.md` の該当タスクにチェックを付け、`CHANGELOG.md` のフォーク節に 1 行

## upstream の取り込み

```
git fetch upstream && git merge upstream/main
python3 build.py && python3 tools/check_page_js.py index.html
```

衝突はフック行に集中するはず。本家側が構造を変えていたら、フックを付け直して `docs/PLAN.md` §1 を更新する。

## やらないこと

- `index.html` などビルド成果物の手編集
- 本家の部品（`11p_*.js`）の挙動変更（バグ修正は本家に PR するか、フォーク側の別ファイルで `J.register` し直して上書き）
- `Math.random()` を描画で使う／全画面 `getImageData`／毎フレームの割り当て
- 素材のバイト列を localStorage や project JSON に入れる
- upstream の URL（`852wa.github.io`）を自分のものに書き換える以外の README 本文の改変（本家の README は「本家の説明」として残す）
