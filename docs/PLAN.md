# my-jizura 改造計画 — 文字PVに画像・動画を入れる

最終更新：2026-09-30　／　対象：upstream [852wa/JIZURA](https://github.com/852wa/JIZURA) v0.10.0（MIT）

この文書は「人が読む計画書」であると同時に、Claude Code（Opus 5.5 / Sonnet 5.5）に実装を任せるときの**作業指示の元ネタ**です。
各フェーズの「タスク」はそのままエージェントへのプロンプトに切り出せる粒度で書いています。作業ルールは [CLAUDE.md](../CLAUDE.md) にあります。

---

## 0. 調査結果と結論

### 0.1 upstream（本家）の現状

- ブラウザ 1 ファイルアプリ（`index.html`、ビルド済み 2.3MB）。ソースは `src/*.js`（40 超ファイル）、UI は `app/body.html` + `app/style.css` + `src/12_ui.js`。
- 歌詞 → カット列（`J.plan`）→ Canvas2D で毎フレーム決定論的に描画（`J.Renderer.frame`）→ WebCodecs + mp4-muxer で MP4 書き出し。
- 860 の表現部品（レイアウト・登場・保持・退場・装飾・加工・背景・カメラ・画面効果・つなぎ）を `J.register()` で登録する「パック」構造（`src/11p_*.js`）。
- After Effects パネル（ScriptUI / CEP）と、AE 用 JSON 書き出しあり。
- 7 言語版（ja/en/zh-hant/zh-hans/ko/id/vi）を `build.py` が生成。
- 開発が非常に速い（1 週間で v0.7 → v0.10、Star 1,100、フォーク 158）。**upstream の更新を取り込み続けられる構造にしておく価値が高い。**

### 0.2 GitHub 上の関連フォーク（画像・動画に関係するもの）

| フォーク | 何をしているか | 使えるか |
|---|---|---|
| [hirazisora/JIZURA](https://github.com/hirazisora/JIZURA)「ONE STOP EDITION」 | **前景・背景に画像・動画を入れる機能を実装済み**。カットごとの素材割り当て、配置・サイズ・角度の編集、動画のループ・開始時刻・クロマキー、素材同梱のプロジェクトファイル（`.jizuraichi`）、レイヤー別タイムライン、素材向けの登場・退場・カメラ演出、ローカル MCP サーバー（エージェントから動画生成）まである | **設計の参考・部分移植の元として最有力**。ただし v0.7 系（707 部品）ベースで本家から大きく乖離（+36,000 行、多言語版は削除、UI を全面改修、コードは圧縮気味）。本家 v0.8〜0.10 で入った文字PV系・キネティック・ホラー・テーマ・LRC・行ロック等が無い |
| [SakiikaVR/JIZURA-AviUtl2](https://github.com/SakiikaVR/JIZURA-AviUtl2) | AviUtl2 のプラグインとしてエンジンを WebView で動かす（Rust/C++） | AviUtl2 を使うなら選択肢。合成は AviUtl 側で行う前提 |
| [paithiov909/JIZURA](https://github.com/paithiov909/JIZURA) | WebMCP を追加 | エージェント連携の参考 |
| [yahnhaagendaz/JIZURA](https://github.com/yahnhaagendaz/JIZURA) | 中日バイリンガル化・独自スタイル追加 | 直接は関係なし |

本家の Issue には「画像・動画を入れたい」という要望は見つかりませんでした（検索範囲内）。本家の思想は「文字だけで見せる」なので、画像・動画対応は**フォーク側で持つのが自然**です。

### 0.3 方針（結論）

**本家 v0.10 をベースに、画像・動画を「メディアレイヤー」として追加モジュールで実装する。hirazisora フォークは設計と難所（動画のフレーム同期・クロマキー・素材同梱ファイル）の参考・部分移植元として使う。**

理由：

1. 本家の更新が速く、部品・機能が増え続けている。本家との差分を「追加モジュール + 少数のフック行」に抑えれば `git merge upstream/main` で追従できる。
2. hirazisora フォークをそのまま使うと、本家 v0.8 以降の機能を捨てることになり、以後の追従もほぼ不可能。
3. 自分用なので、必要な機能（画像・動画）から順に、シンプルに作れる。

代替案（採らないが記録）：

- **hirazisora フォークをそのまま自分用にする**：今すぐ全部使えるのが利点。本家の新機能を諦められるなら最速。「まず触ってみて、欲しい体験を確かめる」用途には今でも使える（https://hirazisora.github.io/JIZURA/）。
- **本家に PR する**：本家の方針（文字だけ）と合わないので採らない。

### 0.3.1 主用途（2026-09-30 確認）

**AI で作った自作曲（Suno / Udio など）に、AI 生成の画像・動画クリップを付けて MV にする。** これを前提に、
Phase 2 には「短いクリップ（5〜10 秒）を曲の長さまで伸ばす」要件（ループ・ピンポン・拍での頭出し）を含め、
Phase 1〜3 の直後の候補は [docs/IDEAS.md](IDEAS.md) の G 節と「おすすめの順番」に従う。歌詞タイミングの取り込み（LRC/Whisper）は Phase 1 と並行して進めてよい。

### 0.4 このリポジトリの状態（Phase 0 完了）

- `upstream/main`（852wa/JIZURA）を履歴ごとマージ済み。以後は `git fetch upstream && git merge upstream/main` で追従する。
- 本家の Search Console 用ファイルは削除。
- リポジトリは公開（Public）にし、GitHub Pages（`main` / root）で `https://hey-taka88.github.io/my-jizura/` から配信する（2026-09-30 決定。スマホでも使うため）。`app/i18n.py` の `BASE` もこの URL（Phase 0.5）。

---

## 1. 今の仕組み（エージェントが最初に知るべきこと）

### 1.1 パイプライン

```
project (JSON)  ──J.parseLyrics──▶ lines ──J.computeTiming──▶ 行の開始時刻
       │                                                          │
       └────────────── J.plan(project, audio) ◀───────────────────┘
                              │
                              ▼
      plan { W, H, fps, duration, cuts[], lines[], events[], style, fx, beats, ... }
                              │
                              ▼
      J.Renderer.frame(ctx, plan, t, opt)   ← プレビュー（rAF）と書き出し（毎フレーム）が同じ関数を呼ぶ
```

- `src/08_planner.js`：`J.defaultProject()`（プロジェクトの全フィールド）、`J.plan()`（カット生成）。`makeCut()` がカットの形（`text start end layout enter hold exit decor treat bg bgP cam camP trans transP morph scheme seed …`）。
- `src/09_render.js`：`frame()` の描画順は次の通り。

```
 1. 背景色 + ラジアルの持ち上げ + 紙テクスチャ          （opt.transparent なら無し。keyBg なら黒）
 2. J.BG[cut.bg].draw()  行ごとの背景グラフィック        （main パスのみ・カメラの影響なし）
 3. 3 パス（B, A = 色ズレのゴースト, main）で drawCut()   （各パスにカメラ変換）
      drawCut: back 装飾 → レイアウト render（歌詞本体）→ front 装飾
 4. モーフ（前カットの字が溶けて移る）
 5. つなぎ J.TRANS（前カットの静止フレーム A と今のフレーム B を合成）
 6. HUD
 7. post()  画面効果（グリッチ・フラッシュ・粒子・周辺減光）
 8. keyFinish()  グリーンバック / ブラックバック用の単色化
```

- 透過 PNG の「前景／後景」分割は `opt.layer = 'back' | 'front'` で `frame()` が描く範囲を切り替えている（`drawCut` 内の `env.layer` 判定）。
- `src/11_export.js`：`encodeMP4()` は `for (i...) { R.frame(ctx, plan, t0 + i/fps, {scale}); venc.encode(new VideoFrame(canvas)) }` の同期ループ（関数自体は async）。PNG ZIP も同様。`J.planForAE()` が AE 用 JSON。
- `src/12_ui.js`：状態は `S`（project, plan, audio, renderer, t, playing…）。`replan()` が `S.plan = J.plan(...)` → 行一覧・タイムライン再描画。`boot()` が初期化。`mergeProject()` が**プロジェクト JSON を信用せず検証**する（色・フォントキー・ロック）。`drawTimeline()` が下部タイムライン。`J.uiApi` に埋め込み用フック（CEP が使う）。
- `src/10_audio.js`：曲は IndexedDB `jizura` / store `files` / key `song` に保存（フォントも `font:<key>`）。**画像・動画もここに `media:<id>` で入れられる。**
- 永続化：`localStorage['jizura.project.v1']` に project JSON（素材の実体は入れない）。

### 1.2 パックの掟（`docs/EXPRESSION_PACKS.md` より抜粋。メディアレイヤーにもそのまま適用）

- 描画は決定論的：`Math.random()` 禁止。乱数は `plan()` の `rng` か `J.r(...)` ハッシュ。
- 1 呼び出し ≈ 2ms（1080p）。全画面の `getImageData` 禁止。毎フレームの canvas 生成禁止（キャッシュ）。
- `ctx` を直接触るときは `ctx.save()/restore()`、ゴーストパスでは `if (env.pass === 'main')` ガード。
- 例外を投げない。`bb === null`、空文字、1 文字、超長文をガード。

### 1.3 ビルドとテスト

```
python3 build.py                       # src/ app/ vendor/ → index.html + 各言語版 + sitemap.xml
node -e "new Function(require('fs').readFileSync('src/08m_media_store.js','utf8'))"   # 構文チェック
python3 tools/check_page_js.py index.html                                             # ビルド後ページの構文チェック
python3 dev/build_test.py all --all-packs && (cd dev/www && python3 -m http.server 8765 &)
python3 dev/smoke_all.py t_all          # 全部品を多数の組み合わせで描画（要 pip install playwright pillow; playwright install chromium）
```

読み込み順は `sorted(glob('src/*.js'))` の文字列順。`08_planner.js` < `08b_omakase.js` < `08m_*.js` < `09_render.js` … `11q_sets.js` < `11z_*.js` < `12_ui.js`。

---

## 2. 目標設計：メディアレイヤー

### 2.1 レイヤー構造

```
 上  ┌────────────────────────┐
     │ post FX（グリッチ等）    │  ← 既存
     │ 前景メディア track=front │  ← 新規（歌詞の上。ロゴ・立ち絵・クロマキー動画）
     │ 歌詞 + 装飾 + HUD        │  ← 既存
     │ J.BG 背景グラフィック     │  ← 既存（メディアの上に薄く重ねるか、消すかを選べる）
     │ 背景メディア track=back  │  ← 新規（写真・B ロール動画）
     │ 背景色・紙               │  ← 既存
 下  └────────────────────────┘
```

### 2.2 データモデル（`project.media`）

```js
project.media = {
  version: 1,
  assets: [                                   // 実体は IndexedDB 'files' の key 'media:<id>'
    { id: 'a1b2', name: 'sea.jpg', type: 'image', w: 4000, h: 2250, size: 812000, hash: '…' },
    { id: 'c3d4', name: 'city.mp4', type: 'video', w: 1920, h: 1080, duration: 42.3, size: 31000000, hash: '…', fps: 30 },
  ],
  tracks: {
    back:  { cuts: [ /* MediaCut */ ], opacity: 1, blend: 'normal' },
    front: { cuts: [ /* MediaCut */ ], opacity: 1, blend: 'normal' },
  },
  autoFill: { back: { mode: 'off'|'perLine'|'perCut'|'perBeat', order: 'sequential'|'random'|'shuffleSeed', loop: true },
              front: { mode: 'off', … } },
  lyricBg: 'over'|'off'|'auto',               // メディアがある区間で J.BG（行の背景グラフィック）をどうするか
  scrim: { mode: 'auto'|'off'|'always', amount: 0.35 },   // 歌詞の可読性のための暗幕（後述）
};

// MediaCut（ユーザーが置いた 1 つの区間）
{
  id: 'k9', assetId: 'a1b2',
  start: 12.5, end: null,                     // end=null は「次のメディアカットまで」。行にリンクする場合は lineRef: { line: 3, cut: 0 }
  fit: 'cover'|'contain'|'custom',            // custom は rect を使う
  rect: { cx: 0.5, cy: 0.5, w: 1.0, h: null, rot: 0, lockAspect: true },   // 画面比 0..1（>1 で画面外もあり）
  opacity: 1, blend: 'normal'|'multiply'|'screen'|'overlay',
  video: { start: 0, loop: true, rate: 1, mute: true },
  chroma: { on: false, color: '#00ff00', tol: 0.3, soft: 0.1 },
  enter: 'auto'|'cut'|'fade'|'slide'|'zoom'|'wipe', hold: 'auto'|'still'|'kenburns'|'pan'|'push'|'drift', exit: 'auto'|…,
  treat: 'none'|'mono'|'sepia'|'blur'|'duotone'|'match',   // match = スタイルの配色に寄せるトーン
  trans: 'auto'|'none'|'<J.TRANS key>',
  seed: 1234, lock: false,
}
```

設計上のポイント：

- **`plan.media`** は `J.plan()` の中で `project.media` から**決定論的**に解決したもの（`end` の補完、`auto` の抽選、`lineRef` → 秒への変換、行の再計算への追従）。描画は `plan` だけを見る。
- 素材のバイト列は `J.mediaAssets: Map<id, { type, element (HTMLImageElement|HTMLVideoElement|ImageBitmap), w, h }>` にメモリ展開。`project` にはメタデータだけ。
- **`mergeProject()` の検証を必ず通す**（本家の方針：プロジェクト JSON は信用しない）。id は `/^[\w-]{1,32}$/`、色は `#rrggbb`、数値は clamp。
- 既存の `plan.cuts`（歌詞）は一切変えない。メディアは別トラック。歌詞側の「背景グラフィック」との関係だけ `lyricBg` で制御。

### 2.3 レンダラーへのフック（`src/09_render.js` に足す行は最小限）

```js
// frame() の 1 と 2 の間
if (J.media && !key && (!layer || layer === 'back')) J.media.drawTrack(ctx, plan, t, 'back', { scale, opt });
// J.BG は plan.media.lyricBg に従って描く／描かない／薄くする
// 6 (HUD) の後、7 (post) の前
if (J.media && !key && (!layer || layer === 'front')) J.media.drawTrack(ctx, plan, t, 'front', { scale, opt });
```

- `J.media.drawTrack()` の中身は `src/08m_media_draw.js`（新規）。カット取得は `J.mediaCutAt(plan, t, track)`（二分探索、`J.cutAt` と同型）。
- 重なりがあるカット（`end` を明示して次と重なる）は下から順に合成。
- keyBg（グリーンバック / ブラックバック）のときはメディアを描かない（単色化されて意味がないため）。透過 PNG 分割では back → `back/`、front → `front/`。
- **可読性の暗幕（scrim）**：背景メディアがある区間で、`scrim.mode==='auto'` なら歌詞 bbox 周辺の平均輝度を**縮小キャンバス（64×36 程度）で 1 秒に 1 回だけ**サンプルし、コントラスト比が足りなければ半透明の暗幕（またはスタイルの `bg` 色の 35%）を歌詞の下に敷く。全画面 `getImageData` は禁止なので縮小版で。

### 2.4 動画のフレーム取得（いちばん難しいところ）

| 場面 | 方法 |
|---|---|
| プレビュー再生中 | `HTMLVideoElement` を `muted` で再生し、`currentTime` と目標時刻のズレを **`playbackRate` の微調整で吸収**（毎回 seek すると decoder が止まる。hirazisora の `J.syncMediaPreview` と同じ考え方）。停止中・スクラブ中は `currentTime = target` で seek |
| 書き出し（MP4 / PNG） | 1 フレームごとに **正確に seek** する：`video.currentTime = t; await 'seeked'` に加えて `requestVideoFrameCallback` が使えるブラウザではそれを待つ。`encodeMP4` のループ先頭に `await J.media.prepareFrame(plan, t, signal)` を 1 行足す（ループはもともと async） |
| 高速・高精度が欲しい場合（Phase 3 以降の任意） | WebCodecs `VideoDecoder` + MP4 デマックス（mp4box.js を vendor に追加）で自前デコード。seek 精度と速度が桁違いになるが実装量が多い |

- 動画は `muted`、音声は使わない（曲は別に読み込む）。**動画の音声を曲として使う**のは「曲として読み込む」ボタンで動画ファイルも受け付ける形で対応（`J.analyzeAudio` は `decodeAudioData` なので MP4 の AAC はそのまま通る）。
- 対応形式はブラウザがデコードできるものだけ（H.264 / VP9 / AV1 の MP4・WebM）。HEVC・ProRes・MOV(ProRes) は環境依存 → 読み込み時に `canPlayType` で判定して案内を出す。
- メモリ：`<video>` は同時に数本まで。使っていない素材は `src` を外して解放（`revokeObjectURL`）。

### 2.5 クロマキー

- WebGL2 のフラグメントシェーダで実装（`src/08m_media_chroma.js`）。入力は video/image、出力は透過の canvas。距離は YCbCr 空間で `tol`（しきい値）と `soft`（境界のなだらかさ）、スピル抑制つき。
- WebGL が使えない環境は CPU 版（縮小したサイズで `getImageData`。プレビューだけ荒く、書き出しはフル）。
- 立ち絵・VTuber 素材・グリーンバック撮影の実写を前景に置く用途。

### 2.6 UI（`app/body.html` + `src/11z_media_ui.js` + `12_ui.js` の少数フック）

- 左列「曲とタイミング」の下に **「画像・動画」セクション**：ドロップゾーン、素材一覧（サムネ・名前・種類・長さ・削除）、「歌詞に合わせて一括配置」（行ごと／カットごと／拍ごと、順番／ランダム、ループ）、トラック切替（背景／前景）。
- **タイムラインに 2 レーン追加**（front / back）：既存 `drawTimeline()` の上下に薄いレーンを足し、クリックでそのメディアカットを選択、ドラッグで開始位置。
- **カット編集ポップオーバー**（選択中のメディアカット）：素材選択、fit、不透明度、合成、動画の開始秒・ループ、クロマキー ON/色/しきい値、登場・保持・退場・加工・つなぎ、ロック。
- **配置編集モード**：プレビュー上に枠を出し、ドラッグ移動・四隅でサイズ・外側で回転。適用範囲「このカットだけ／以降すべて」。
- かんたんモードでは「画像を入れる」ボタン + 「背景に写真を使う」トグルだけ（自動配置 perLine）。
- スマホモードは Phase 4 以降（最初は非表示）。
- `12_ui.js` 側のフックは 4 か所を目安に：`boot()` で `J.mediaUI?.init(api)`、`replan()` の最後で `J.mediaUI?.onPlan()`、`drawTimeline()` の最後で `J.mediaUI?.drawLanes(x, X, T, w, h)`、`mergeProject()` で `o.media = J.media ? J.media.normalize(p && p.media) : undefined`。

### 2.7 保存・読み込み

- 自動保存：project JSON は今まで通り localStorage。素材は IndexedDB（`media:<id>`）。起動時に `assets` の id を IndexedDB から復元し、無いものは「素材が見つかりません」と表示（カットは残す）。
- **素材同梱ファイル `.jizura.zip`**（Phase 4）：`project.json` + `assets/<id>.<ext>` + 任意で `song.<ext>`。書き込みは `11_export.js` にある無圧縮 ZIP ライタを共用。読み込みは自前の小さな ZIP パーサ（store のみ）。4GB / 65,535 ファイル制限は既存のチェックを流用。
- AE 用 JSON：`plan.media` をそのまま含める（Phase 4 で AE パネル側にフッテージ読み込みを追加）。

### 2.8 おまかせ・部品との関係

- おまかせ（`08b_omakase.js`）は歌詞側のみ。メディアは `autoFill` と `auto` 指定の抽選で「メディアのおまかせ」を別に持つ（`J.media.randomize(project, rng)`）。
- 背景メディアがある区間では、`busy: true` のレイアウト（画面を埋める）と派手な `J.BG` を抑える重み付けを `pickBg` / レイアウト抽選に**小さなフック**で入れる（Phase 4）。
- メディアの登場・退場は歌詞の `J.TRANS` を再利用できる（`draw(ctx, A, B, p, info)` はデバイスピクセルの canvas 2 枚を合成する契約なので、素材同士にもそのまま使える）。

---

## 3. フェーズ計画

各フェーズは 1〜数 PR。PR ごとに「受け入れ条件」を満たすまでをタスクとする。ファイル名は提案（変えてよいが、読み込み順の制約に注意）。

### Phase 0 — リポジトリ整備（このPRで完了）

- [x] upstream を履歴ごと取り込み、`upstream` リモートを設定
- [x] `docs/PLAN.md`（本書）、`docs/IDEAS.md`、`CLAUDE.md`

### Phase 0.5 — 開発環境と公開先（Sonnet・小）

- [x] `app/i18n.py` の `BASE` を自分の Pages URL（`https://hey-taka88.github.io/my-jizura/`）に変更し、`python3 build.py` で `sitemap.xml`・canonical を更新
- [ ] Settings → Pages で `main` / `/ (root)` を配信元にする（リポジトリ所有者が手で行う。エージェントからは設定できない）
- [x] `dev/requirements.txt`（playwright, Pillow）と、`python3 -m playwright install chromium` の手順を CLAUDE.md に追記。`dev/smoke_all.py t_all` が通ることを確認（ベースライン：860 部品、problems 0、page errors なし。`node dev/ae_test.js` も problems 0）
- [x] Claude Code on the web 用の SessionStart フック（`.claude/hooks/session-start.sh`）で、上記の Python パッケージと `dev/` の npm パッケージを自動で入れる
- [x] PR 時に既存ブラウザテストとビルド・構文・生成 HTML の一致を検査する GitHub Actions と共通ランナーを追加。Codex の作業・レビュー観点は `AGENTS.md`、運用と手動確認の境界は [CI.md](CI.md)
- [x] `CHANGELOG.md` の先頭に「フォーク（my-jizura）」節を作り、以後フォーク側の変更はそこに書く（本家の節は触らない）
- 受け入れ：`python3 build.py` が成功、ページの canonical が自分の URL、smoke が「problems: 0」

### Phase 1 — 静止画の背景（MVP）（Sonnet 実装 / Opus レビュー）

**状態：完了（2026-10-01）。** 実装は `src/08m_media_model.js`・`08m_media_plan.js`・`08m_media_store.js`・`08m_media_draw.js`・`11z_media_ui.js`。本家ファイルへの変更は `08_planner.js`（2 行）・`09_render.js`（3 行）・`12_ui.js`（5 行）だけ。確認は `python3 dev/media_e2e.py`（21 項目）と `dev/smoke_all.py` のメディア付きの組み合わせ。
計画との違い：
- UI の節は `11z_media_ui.js` が実行時に作って「行とカット」の上に差し込む（`app/body.html`・`app/style.css` は本家のまま。CSS も同じファイルから `<style>` で足す）。
- `tracks.<track>.dim`（暗さ 0〜0.9、背景は初期値 0.25）を追加。歌詞を読みやすくする簡易版で、Phase 3 の暗幕（scrim）までのつなぎ。
- 行ごとの指定は `tracks.back.cuts` に `lineRef: { line }` 付きのカットとして入る（`assetId: ''` は「画像なし」）。自動の並びは `autoFill.back.seed` で決まり、おまかせでは変わらない。
- 同じ画像が続く行はひとつのカットにまとめる（ゆっくり寄る動きが途中で戻らない）。次の画像は 0.6 秒でクロスフェード。
- 英語以外の言語版の UI 文字列は、`11z_media_ui.js` の中で英語にしている（`app/english.py` の対応表は使っていない）。
- タイムラインの画像の帯は表示だけ（クリック・ドラッグは Phase 3 の配置編集と一緒に）。

1. **素材ストア** `src/08m_media_store.js`
   - `J.media.addFiles(files)`：画像を `createImageBitmap` で読み、`{id,name,type:'image',w,h,size,hash}` を返す。id は内容ハッシュ（SHA-256 の先頭 8〜12 文字）で重複排除
   - IndexedDB `files` に `media:<id>` = `{name,type,data}`。`J.media.restore(project)` で起動時に復元。`J.media.remove(id)`
   - `J.mediaAssets` Map。`ImageBitmap` は `close()` で解放
2. **スキーマと検証** `src/08m_media_model.js`
   - `J.media.defaults()`、`J.media.normalize(m)`（§2.2 の全フィールドを検証・clamp）。`J.defaultProject()` に `media` を足す（`08_planner.js` に 1 行）。`mergeProject()` に 1 行
3. **プラン解決** `src/08m_media_plan.js`
   - `J.media.resolve(project, plan)` → `plan.media = { back: {cuts:[…start,end 確定…]}, front: {…} }`。`J.plan()` の最後に 1 行フック。`autoFill.perLine` は `plan.lines` の開始時刻に素材を順に（またはシード付きランダムに）割り当てる
   - `J.mediaCutAt(plan, t, track)` 二分探索
4. **描画** `src/08m_media_draw.js`
   - `J.media.drawTrack(ctx, plan, t, track, o)`：cover / contain / custom rect、opacity、blend。`enter/exit` は最初は `cut` と `fade` だけ、`hold` は `still` と `kenburns`（ゆっくり寄り）だけ
   - `09_render.js` に §2.3 の 2 フック。`lyricBg: 'off'` のとき `J.BG` をスキップ
   - `opt.layer` の back/front 分割に対応
5. **UI** `src/11z_media_ui.js` + `app/body.html` + `app/style.css`
   - ドロップゾーン＋素材一覧、「歌詞に合わせて一括配置（行ごと）」、トラックは背景のみ、`lyricBg` トグル、素材の削除
   - 行一覧の各行に「背景：〈素材名〉▾」のセレクトを足し、行ごとに素材を差し替えられる（`lineRef` 方式）
   - タイムラインに back レーン 1 本
6. **書き出し**：MP4 / PNG / 透過 PNG（前景／後景）で背景メディアが出ることを確認（静止画なので `prepareFrame` は不要）
7. **テスト**：`dev/test.html` の `T` に `T.addMediaFixture()`（1×1 の色付き画像を data URL で登録）を足し、smoke に「メディアあり」の組み合わせを 1 セット追加。`python3 tools/check_page_js.py index.html`
- 受け入れ：写真 5 枚を落として「一括配置」→ 行ごとに背景が切り替わる MP4 が書き出せる。素材はリロード後も残る。プロジェクト JSON に素材の実体が入らない。keyBg ON のときは描かれない。既存の smoke が壊れない

### Phase 1.5 — 歌詞タイミングの取り込み（Phase 1 と並行可・Sonnet・小）

**状態：完了（2026-10-01）。** `src/11y_lyrics_import.js` が SRT・VTT・JSON（Whisper の segments、Suno の aligned_words、WhisperX などの単語リスト、`[{ start|time, text }]`）と拡張 LRC を LRC に変換し、本家の「LRC を読み込む」（元に戻す付き）に渡す。本家ファイルの変更は `12_ui.js` 1 行。確認は `python3 dev/lyrics_import_e2e.py`。
計画との違い：語ごとの時刻は最初は保存しなかった（2026-10-03 に「語の時刻」で保存するようにした。下の実制作フィードバック 2 回目）。`[Verse]` `[Chorus]` などの見出しは空行（＝新しいまとまり）に、JIZURA が読めない間奏タグ（`[Instrumental Break]` など）は `[間奏]` にする。単語の時刻から行を作るときは、単語の中の改行・0.9 秒以上の間・文末＋0.3 秒の間で区切る。

- [x] LRC 読み込み（本家 v0.10）を拡張し、SRT / VTT / Whisper の JSON（`segments[].words[]` の word timestamps）を読めるようにする。Suno のタイムスタンプ付き歌詞（LRC または JSON）も対象
- 受け入れ：Whisper の JSON を落とすと、タップ同期なしで行が合う。既存の LRC 読み込みの挙動は変わらない

### Phase 2 — 動画（Sonnet 実装 / Opus レビュー。難所は Opus が設計）

**状態：完了（2026-10-01）。** 実装は `src/08m_media_video.js`（要素の管理・プレビュー同期・書き出し時の正確なシーク）と、`08m_media_plan.js` の `M.videoTimes`（曲の時刻 → クリップの時刻）、`08m_media_store.js`・`08m_media_draw.js`・`11z_media_ui.js` の追加分。本家ファイルの追加は `12_ui.js` 1 行（`tick()`）と `11_export.js` 2 行（MP4・PNG のループ）。確認は `python3 dev/video_e2e.py`（フレームごとに時刻を色で埋め込んだクリップを使い、プレビュー・再生中の追従・4 つの伸ばし方の書き出し・継ぎ目のクロスフェード・PNG・再読み込みを確認）。
計画との違い・まだ確かめていないこと：
- `requestVideoFrameCallback` は待っていない（Chromium では `seeked` の直後に正しいフレームが描けることをテストで確認。Safari で違えば足す）。`canPlayType` での事前判定もしない（実際に読み込んで 1 フレーム描けるかで判定）。書き出しの進捗に「動画のフレーム待ち」は出していない
- 伸ばし方・速さ・頭出しの拍数は、今は全体で 1 つの設定（カットごとの設定はデータの形だけ用意。編集 UI は Phase 3 の配置編集と一緒に）
- 同時に読み込む動画は最大 3 本（今の・前の・次の）。動画にはゆっくり寄る動きを付けない（明示したときだけ）
- 確認は Chromium（GPU なしのクラウド環境）・VP9 の 320×180 クリップ・24fps の書き出し。**1080p の H.264 クリップ、30fps の書き出し、Safari / iPad はまだ確かめていない**（受け入れ条件のうち実機で見るもの）

1. `addFiles` で動画を受け付ける：`<video muted playsinline preload="auto">` + `loadedmetadata` で `w,h,duration`。`canPlayType` で不可なら案内。サムネは 1 秒目を canvas に描く
2. プレビュー同期 `J.media.syncPreview(plan, t, playing)`：§2.4 の playbackRate 吸収。`12_ui.js` の `tick()` から 1 行呼ぶ。停止・スクラブは seek
3. 書き出し `J.media.prepareFrame(plan, t, signal)`：`seeked` + `requestVideoFrameCallback` 待ち。`encodeMP4` / `exportPNGZip` のループ先頭に `await` を 1 行。進捗に「動画のフレーム待ち」を出す
4. カット設定：`video.start`（素材のどこから）・`loop`・`rate`。`end` が素材より長いときの伸ばし方を選べる：`extend: 'loop' | 'pingpong' | 'hold' | 'beat'`（`beat` = 小節（または N 拍）ごとに `video.start` へ頭出し。AI 生成の 5〜10 秒クリップを曲の長さまで使うための要件）。ループの継ぎ目は短いクロスフェード（0.2〜0.4 秒）で隠す
5. メモリ管理：同時に `src` を持つ video は「今のカット＋次のカット」だけ。それ以外は解放
6. 動画ファイルを「曲として読み込む」で音声だけ取り出せるようにする（`loadAudioFile` の accept に video を足す。`decodeAudioData` はそのまま）
- 受け入れ：8 秒の AI 生成クリップ 1 本を 3 分の曲全体に `pingpong` と `beat` で敷いて破綻しない。1080p30 の MP4 を 2 本置き、24fps / 30fps の両方で書き出したときに**フレームの取りこぼし・重複が無い**（書き出し MP4 を `ffprobe -show_frames` などで確認、または画面に時刻を焼き込んだテスト動画で目視）。プレビューでカクつかない（1080p で 24fps 維持）。iPad Safari でクラッシュしない（素材 2 本まで）

### Phase 2.5 — エージェントから操作する（CLI → MCP）（Opus 設計 / Sonnet 実装）

**状態：完了（2026-10-01）。** `tools/jizura_driver.py`（土台）・`tools/jizura_cli.py`（`render` / `preview` / `plan` / `info`）・`tools/jizura_mcp.py`（17 ツール）。使い方は [docs/MCP.md](MCP.md)。
確認は `python3 dev/mcp_e2e.py`（作業フォルダに WAV・Suno 形式の歌詞・画像 3 枚を作り、本物の MCP クライアントから全ツールを通す。mcp 1.x と 2.x の両方）。本家ファイルの変更なし（`11z_media_ui.js` に `J.mediaUI.addFiles` / `remove` を足しただけ）。
計画との違い・まだ確かめていないこと：
- MCP サーバーは `mcp/server.py` ではなく `tools/jizura_mcp.py`。リポジトリ直下に `mcp/` フォルダを置くと、Python の `mcp` パッケージと名前がぶつかって読み込めなくなることがあるため
- ドライバーはページ内の関数（`J.ui` / `J.uiApi` / `J.mediaUI` / `J.exportMP4`）を呼び、ファイルは隠しの `<input type=file>` から渡す。新規作成・プロジェクトを開くは「開く」のファイル入力を通す（`mergeProject` の検証をそのまま使うため）。書き出しはページのダウンロードを受け取って保存
- ブラウザは Chrome → Edge → Playwright の Chromium の順に使う（H.264 の読み書きは Chrome / Edge だけ）。**このクラウド環境には Chrome がないので、Chrome での実行（H.264 のクリップ・H.264 の書き出し）は未確認**
- 歌詞を入れ直すと、行ごとの画像の指定も消す（行が変わるため。パネルの「LRC を読み込む」は消さない）
- `set_look` の案の番号は、おまかせを番号から作った乱数で引く（同じ状態から同じ番号なら同じ見た目。おまかせは「今と違う」を選ぶので、今の見た目が違えば結果も変わる）
- 書き出しの進み具合は MCP の progress 通知で送る（受け取るかはクライアント次第）。長い曲はクライアントの待ち時間（Claude Code の `MCP_TOOL_TIMEOUT`、Codex の `tool_timeout_sec`）を延ばす
- アルバム単位の一括書き出し（IDEAS の G9）・連番 PNG の書き出しは、まだ CLI にない
- Claude Desktop・Codex からの実際の接続は未確認（プロトコルは `dev/mcp_e2e.py` のクライアントで確認）

目的：「この曲・歌詞・画像フォルダで、しっとり系の 16:9 と 9:16 を書き出して」を Claude（Claude Code / Claude Desktop）や Codex に頼めるようにする。
アプリはブラウザの中で全部動くので、**見えないブラウザ（Playwright の headless Chromium）でビルド済みの `index.html` を開き、`J.*` の関数を呼ぶ**のが土台になる。
`dev/media_e2e.py` がすでにこの形（画像を入れる → 再生位置のフレームを見る → MP4 を書き出す）なので、それを道具として切り出す。

1. **土台 `tools/jizura_driver.py`**：ページを開いて操作する関数の集まり。`new_project(lyrics, title, artist, aspect)`、`load_song(path)`、`import_timing(path)`（Phase 1.5 の変換を通す）、`add_pictures(paths)`、`set_line_picture(line, name | none)`、`set_look(style | theme | おまかせ)`、`get_plan()`（行・カット・画像の一覧）、`preview(times, scale)`（フレームの PNG）、`export_mp4(out, res, range)`、`save_project(path)`
2. **CLI `tools/jizura_cli.py`**：`python3 tools/jizura_cli.py render --lyrics song.lrc --song song.mp3 --pictures ./pics --aspect 9:16 --theme ballad --out mv.mp4`。Claude Code はこれを Bash で呼べる（MCP なしでもここで実用になる）。アルバム単位の一括書き出し（IDEAS の G9）もここに足す
3. **MCP サーバー `mcp/server.py`**（Python の `mcp` SDK、stdio）：上の関数をそのまま MCP のツールにする。`preview` は画像を返すので、モデルがフレームを**見て**「文字が写真に埋もれている → 暗さを上げる」のように直せる
   - 読み書きできる場所は、設定した作業フォルダ（`JIZURA_WORKDIR`）の中だけにする。ネットワークには出ない（フォントの取得を除く）。既存ファイルは上書きしない
   - 設定例を README に書く（Claude Desktop・Claude Code の `claude mcp add`・Codex CLI の `config.toml`）
4. **参考**：hirazisora フォークの `mcp/`（Node + Playwright、MIT）。移植するより、このフォークの `J.media` に合わせて小さく作り直す方が保守しやすい

- 受け入れ：Claude Code から `jizura` の MCP ツールだけで、AI 曲（mp3）＋ Suno の歌詞 JSON ＋ 画像 5 枚から、16:9 と 9:16 の MP4 が作業フォルダに出る。途中で `preview` の画像をモデルが確認できる
- 順番：Phase 2（動画）の後がおすすめ（ツールの形が動画素材込みで決まるため）。急ぐなら 1 と 2 だけ先に作ってもよい

### Phase 3 — 前景レイヤー・クロマキー・演出（Opus 設計 / Sonnet 実装）

**状態：3a（演出：3・4・6・7）完了（2026-10-01）。3b-1（前景：1）・3b-2（クロマキー：2）完了（2026-10-05）。3b-3（配置編集：5）完了（2026-10-06）。Phase 3 はすべて完了。**
3b-3 の実装：`src/11z_media_place.js`（新規）。「画像・動画」の欄に「前景（歌詞の上）」の一覧（開始・終了・不透明度・クロマキー（なし／自動／スポイト）・抜く範囲・緑のふち・中央に戻す・外す）。素材の一覧の「前」で曲全体に前景として置き、選んだものにはプレビューの上に枠が出る（中をドラッグで移動、角で大きさ（形はそのまま）、上のつまみで回転、Shift で 15° ずつ）。ドラッグ中はプロジェクトと計画の配置を更新して描き直し、離したときに計画を作り直す。キャンセルでは両方を元に戻す。スポイトは、プレビューの合成結果ではなく素材そのものの色を拾う。前景に置いた素材は、背景の自動の切り替えに使わない（`08m_media_plan.js`）。計画のカットに元のカットの `id` を持たせた。確認は `python3 dev/place_e2e.py`（マウスで操作して確認。CI にも入れた）。計画の「このカットだけ／以降すべて」と、背景（back）の配置編集はまだ
3b-3 のレビュー確認：描画と採色は `M.cutBox` の変換とwipeの表示領域を共用する。動画は再生を停止し、選択カットの `videoTimes` の時刻を既存のフレーム処理を使う `prepareCut`／`videoCap` で読み取る。新たなデコーダーは作らず、ループ境界では描画と同じ2フレームの合成色を採色する。採色では選択カットを表示区間外でも準備し、書き出し用のクールダウンを残さない。共有デコーダーのフレーム準備は直列に処理する。同じ動画の異なる時刻を重ねる通常プレビューも、カットごとのフレームを再利用キャンバスに保持する。シークで古い読み取りを中断し、再生中は最新の要求を引き継ぐ。提示フレームの待機がタイムアウトした場合は採色・書き出しで古い画素を使わない。モード変更・選択解除でスポイトを終了し、待機中の動画採色も中断する。ドラッグのキャンセルは元の rect の有無と保存値も復元する。`dev/place_regression_e2e.py` をCIに追加。
3b-2 の実装：`src/08m_media_chroma.js`（新規）。カットの `chroma` = `{color: '#rrggbb' | 'auto', tol, soft, spill}`。色の近さは YCbCr の色の成分だけで測る（影になった部分も同じように抜ける）。`auto` は素材の上のふちと左右のふちの色の中央値（下のふちは人物が立っていることが多いので使わない）を、素材ごとに 1 回だけ小さな写しから求める。WebGL2 で処理し、使えないときは同じ計算を 960px 以下の写しで CPU で行う（全画面の `getImageData` はしない）。画像は 1 回抜いて持ち続け、動画はクリップごとの 1 枚のキャンバスに毎フレーム。抜いたあとに加工（モノクロなど）をかけても透明な部分は透明のまま。GPU のないこのコンテナでは、1280px の動画 1 コマあたり約 30ms 増える（GPU のある PC ではずっと小さいはずだが、まだ測っていない）。計画の「スポイト」（プレビューで色を拾う）は 3b-3 の画面で作る
3b-2 の回帰確認：キーの設定が変わった画像は内容の版を更新し、加工のキャッシュも描き直す（キャンバスは再利用）。`dev/chroma_e2e.py` で WebGL／新しい素材への CPU 処理、設定を A→B→A と戻す場合を確認。`dev/front_e2e.py --require-export` で別の色を抜いた同一画像を同時に重ね、プレビューと MP4 を確認。どちらも PR の CI で実行する。
3b-1 の実装：`08m_media_model.js`（カットの `rect` = `{x, y, w, rot}`。x / y は画面の中心からのずれ（±0.5 で端、±1 まで）、w は画面の幅に対する幅（0.02〜4）、rot は度。計画の §2.2 の `cx/cy 0..1` から、歌詞の位置（`set_line_style` の x / y）と同じ決め方に変えた）、`08m_media_plan.js`（前景は「重ねられる」：時刻で置いたものどうしが重なってよく、終わりなしは曲の最後まで、つなぎなしでそれぞれがフェードで出入り。`M.cutsAt`）、`08m_media_draw.js`（`rect` のカットはその位置・大きさ・回転で描く。前景は出ているものを全部、始まった順に描く）、`08m_media_video.js`（書き出しで前景の動画もすべて正確な位置に）。前景は HUD のあと・ポスト効果の前、透過 PNG では前景の層だけ、グリーン／ブラックバックでは描かない（いままでの通り）。MCP は `add_timed_media(track='front', x, y, size, rot, opacity, enter, exit, hold)`、CLI は `--front-media`。確認は `python3 dev/front_e2e.py`。Web の画面からの操作は 3b-3 で追加
3a の実装は `src/08m_media_look.js`（加工・暗幕、新規）、`08m_media_draw.js`（動き・登場退場・つなぎ）、`08m_media_plan.js`（カットごとの決定）、`08m_media_model.js`（値と検証）、`11z_media_ui.js`（選択肢とおまかせ）。本家ファイルの変更なし。確認は `python3 dev/media_look_e2e.py`。
計画との違い・まだ確かめていないこと：
- つなぎは「クロスフェード／パッと切り替え／いろいろ（`mix`）／効果を 1 つ指定」。`mix` は歌詞の `J.TRANS` から**画像に向く 16 種**（`M.TRANS_KEYS`）だけをシードで選ぶ（文字向けの効果は除外）。タグでの抽選はしていない
- 登場・退場は「前後に画像が接していないとき」だけ（行に画像なしを挟んだとき・最初と最後）。接しているときはつなぎが決める。パネルでは登場と退場を同じ値にする（別々の指定はドライバーと MCP から）
- 加工は `ctx.filter` を使わず合成モードだけで作る（Safari でも同じ見た目）。画像は 1 回作って持ち続け、動画は毎フレーム最大 1280px で作る。`match` は「スタイルの色に寄せる」（色相を寄せる＋紙の色を薄く重ねる）、`duotone` はスタイルの暗い色と明るい色の 2 色
- 暗幕：歌詞の位置は、歌詞のカットごとに 1 回だけ小さく描いて文字の位置を記録して求める（plan ごとに保持。小さい飾り文字は除く）。「読みにくいときだけ」は、画像の明るさの小さな表（画像ごとに 1 回）と文字色のコントラスト比 4.5 で決める。色はスタイルの背景色。歌詞のカットが続くときは前の暗幕から入れ替わる
- 動き・加工・登場・つなぎの**カットごとの指定**（データの形はある）を編集する画面は 3b の配置編集と一緒に作る
- GPU のないクラウド環境で、1080p の 1 コマあたり：加工・暗幕はほぼ増えない（誤差 ±5ms の範囲）、つなぎの効果中はクロスフェードより +7ms 程度

1. front トラック（§2.1）。HUD の後・post の前に描く。透過 PNG の `front/` に含める
2. クロマキー `src/08m_media_chroma.js`（WebGL2、CPU フォールバック）。カット設定に ON/色/しきい値/なだらかさ。スポイト（プレビューをクリックして色を拾う）
3. 登場・保持・退場・加工の拡充：`fade slide zoom wipe` / `still kenburns pan push drift beatPulse` / `none mono sepia blur duotone match`。`match` はスタイルの `bg`/`accent` に寄せた 2 色トーン
4. つなぎ：`J.TRANS` の再利用（素材同士）。`trans:'auto'` は `J.TRANS_ORDER` から `tags` で抽選
5. 配置編集モード（プレビュー上でドラッグ・リサイズ・回転）
6. 可読性の暗幕（§2.3 scrim）
7. 「メディアのおまかせ」ボタン（配置パターン・保持・つなぎをシードで振り直し）
- 受け入れ：グリーンバックの立ち絵動画を前景に置き、歌詞の上で抜けている MP4 が出る。scrim ON で白背景の写真の上でも白文字が読める。全部品の smoke が通る

### 実制作からのフィードバック（2026-10-02、Codex が MCP で「あの日の青」を制作）

30 行の歌詞と曲全体の背景動画 1 本で MV を作った報告から。1 曲専用の値（カット数・配色・文字サイズ）はアプリの規則にしない。中央の大きな文字など、文字が主役の表現も残す。

- [x] **P0 保存したファイルの再利用**：`save_project` / `export_mp4` は `{requested, saved, collision: new|renamed|replaced}` を返す。`replace=true` は、このサーバーが今回書いたファイルだけ上書き（前からあるファイルは上書きしない方針はそのまま）。`open_project` / `get_plan` は読み込まれていない素材を `missing` に出す
- [x] **P0 曲の時刻で置く背景**：`add_timed_media` / `remove_timed_media`（CLI は `--timed-media 名前@開始-終了`）。優先順は「行ごとに選んだ画像 ＞ 時刻で置いた画像 ＞ 行ごとの自動」。時刻で置いた動画は `anchor`（置いた時刻）から曲の時計で流れ、行や割り込みで頭に戻らない（`M.videoTimes` が `c.anchor` を使う）。時刻で置いたカットが無いプロジェクトの計算は変わらない
- [x] P2 書き出しの長さ：`duration`（予定）・`frames` / `videoDuration`（書いた整数フレーム）・`audioDuration` を別々に返す
- [x] P1 文字組みを直接固定する操作：`get_line` / `set_line_style`（CLI `--line-style`）。配置・動き・カメラ・背景グラフィック・装飾・カット数・句の開始時刻・固定は本家の `overrides`（行）と `cutTech`（カット）に書く。位置・大きさ・文字色は本家に無いので `project.media.text.lines` に持ち、計画のあとで当てる（`src/08m_media_text.js`：文字だけを動かす特別なカメラ `place`（おまかせでは選ばれない）と、その行用の配色の複製）。プレビューは 1 つの描画器を使い回すので、同じ作業の中では保存→開き直し後も同じ画素になる（本家の紙・粒子の質感は描画器ごとにランダムに作られるため）。**Web の画面からは、位置・大きさ・色はまだ変えられない**（Phase 3b の配置編集で）
- [x] P1 素材の再リンク：`relink_media`（CLI `--relink`）。素材の id は中身の SHA-256 の先頭 12 桁なので、名前が変わっても見つかる。素材込みの書き出し（`.jizura.zip`）は Phase 4
- [x] P1 間奏でタイトルを出すかどうか：`set_text_options(interlude_title=false)`（CLI `--no-interlude-title`）。`project.media.text.interludeTitle`。本家のファイルは変えず、計画のあとで間奏のカットの曲名だけを消す。Web の画面にはまだ無い
- [x] P2 制作の記録（run manifest）：MCP サーバーが作業フォルダの `jizura_runs/<日時>_<名前>/` に `report.md`（日本語）・`run.json`・`calls.jsonl`・`previews/`・`projects/` を残す（`tools/jizura_runlog.py`）。環境（版・commit・ページの sha256・ブラウザ）、時間（ツールの中／ツールとツールのあいだ、段階ごと）、読んだ・書いたファイルの sha256、プレビュー・書き出しに使ったプロジェクトの状態、`log_note` のメモ（近いプレビュー画像つき）、断った呼び出し。CLI にはまだ無い

### 実制作からのフィードバック 2 回目（2026-10-03、Codex が MCP で 39 行の MV を A〜D の比較試写から改訂）

文字を小さな一行字幕に寄せず、JIZURA の標準の動き（分割・拡大・回転・反復・残像）を活かす方向。ランダムは候補を作る入口で、採用した区間は固定して、色・読みやすさ・語の時刻だけを局所的に直したい、という報告から。

- [x] **語の時刻**：単語ごとの時刻（Suno の `aligned_words`、WhisperX などの単語リスト、拡張 LRC の `<mm:ss.xx>`）を `project.media.text.words` に `{text, start, w:[[時刻, 行の中の文字位置]], p}` として残し（素材と同じく検証・上限つき）、計画のあとで、行の中の 2 つ目以降のカットの開始を、その句の最初の文字を歌う時刻へ動かす（`src/08m_media_text.js` の `M.alignWords`）。文字位置は空白・`/`・`*`・`|` の注釈・末尾の `!` を数えない（本家が句に分ける前の文字）。手で決めた句の開始時刻（`cutTime`）が優先、行をもう一度出すカット（recap）は動かさない、句が行の文字の並びと合わないときと、歌詞を手で書き換えて語の文字と合わなくなった行は今まで通り文字数で配分。カットの数・順序・抽選は変わらない（時刻だけ）。「LRC を読み込む」でも MCP の `set_lyrics` でも同じ。`get_line` / `get_plan` に `words`・`confidence`（行でいちばん低い合わせの確かさ）・`cutTimes`。確認は `dev/text_style_e2e.py` の「語の時刻」
- [x] Codex 側で足した `get_motion_plan`（読み取り専用）・`lock_motion_palette`（範囲の行の動きとカット境界を固定）を取り込んだ（2026-10-04、引き継ぎ v02）。Codex 版との違い：行番号は他のツールと同じ **1 始まり**（Codex 版は 0 始まり）、カットごとに行の中の番号・recap・固定の有無を返す。色は渡したときだけ変える（Codex 版の既定値 `#35465a` などは 1 曲用の値なので外した）、変えたものは `global` に「プロジェクト全体」として返す。`lock=false` で外せる。どちらも `@recorded`（取得は check、固定は edit）
- [x] 固定で句の境界がずれる問題：本家の行ロック（`J.lineSnapshot` だけ）では、recap を含む行の句の開始時刻が動く（`08_planner.js` がロックした recap を文字数で重み付けし直すため。例：9.91 → 9.17 秒）。`M.lockLine`（`src/08m_media_text.js`）が句の時刻を `overrides.cutTime` にも入れ、足した分を書いた値ごと `media.text.lines[行].heldTimes` に記録する。外すとき（MCP・アプリのロックボタンどちらでも）は、足したときの値のままのものだけ消す（手で決めた時刻と、固定のあとに手で直した時刻は残る）。`set_line_style(lock=True)` も同じ。固定した行への `set_line_style` は、位置・大きさ・文字色だけなら固定もカットも時刻もそのまま、配置や動きなどカットそのものを変える指定なら、その行を組み直して固定し直す（Codex レビュー、PR #10）。**アプリのロックボタンで固定したときは、まだずれる**（本家のバグ。本家に報告するか、フォーク側で直すかは未定）
- [x] `timing_master.json` の形（`lines[].words`）と、単語付きの Whisper の segments を語の時刻として読む。語ごとの確かさを残し、0.1 未満の語と行の外の語は句の切り替えに使わない（前後の使える語から割り出す）。`set_word_times` で歌詞を変えずに語の時刻だけを入れ替えられる
- [ ] 行の表示が歌より短い行（`off`）：本家の `visEnd`（行の文字数で表示の長さを決める）より長く歌う行は、後ろの句が歌う時刻まで待てない。「つまみ」では 39 行中 8 行。表示を延ばすか、句を詰めるかは見て決める
- [x] 範囲単位の見せ方の強さ：`set_range_style(開始, 終了, tone)`（CLI `--range-style`）。範囲は秒で指定（聴いて「ここは静かに」を渡せるように。歌詞の見出しで指定する方法は必要になったら）。`quiet` / `calm` の中身は `src/08m_media_text.js` の `M.TONES`（どの曲にも使える型。1 曲用の値は入れない）で、本家の行ごとの設定（配置・登場／退場・保持・カメラ・加工・装飾・カット数、カットごとの「つなぎなし」）として書くので、計画は本家のまま。画面効果だけは本家に行ごとの設定がないので、計画のあとで、その行が出ているあいだの効果を外す。`project.media.text.lines[行].tone` に残り、`get_line` / `get_plan` / `get_motion_plan` に `tone` として出る。範囲の外の行も変わることがある（本家が直前に使った部品を避けるため）ので、変わった行を `othersChanged` で返す
- [ ] 文字色以外の局所的な配色（いまの `colors` / `chroma` はプロジェクト全体）
- [x] 確かさの低い行を一覧で出す：`set_word_times` の `weak` と、`get_line` の語ごとの `p` / `used`。耳での確認（歌と合っているか）はツールではできない
- 読みにくいカットだけ配置を替える：`set_line_style(行, cut=…, layout=…)` で今もできる
- 採用案の保存：`save_project` のプロジェクトに `cutTime`・固定・語の時刻が入る。制作の記録の `projects/` にもプレビュー・書き出しのたびに残る

### Phase 4 — 統合・仕上げ

1. 素材同梱ファイル `.jizura.zip`（保存・開く・「素材が足りない」の警告）
2. かんたんモード／スマホモードの導線（最小）
3. 英語版：`app/english.py` に新しい UI 文字列を追加（`tools/check_i18n.py` が英語以外の版で警告する場合は、新規文字列を日本語のままにしておく方針でも可 — 自分用なので）
4. おまかせとの連携（§2.8 の重み付け）
5. AE 用 JSON に `media` を含め、AE パネル側でフッテージを配置（`ae/50_build.jsx`）。CEP 版で素材のパスを渡す。**任意**（AE を使わないなら飛ばす）
6. README（フォーク節）と CHANGELOG
- 受け入れ：別 PC のブラウザで `.jizura.zip` を開いて同じ MP4 が書き出せる

### Phase 5 以降 — [docs/IDEAS.md](IDEAS.md) から選ぶ

---

## 4. エージェント運用（Opus 5.5 / Sonnet 5.5）

### 4.1 役割分担の目安

| 作業 | モデル | 理由 |
|---|---|---|
| フェーズの詳細設計（データ構造・フックの位置・難所の方式決定）、PR レビュー、バグの根本原因調査 | Opus 5.5 | 既存コード（特に `09_render.js` の 540 行と `12_ui.js` の 1,900 行）を読み切って副作用を見抜く必要がある |
| 区切られたタスクの実装、UI の組み立て、テスト追加、i18n、ドキュメント | Sonnet 5.5 | 仕様が固まっていれば速く正確 |
| 動画同期（Phase 2-2/2-3）とクロマキー（Phase 3-2） | Opus 5.5 で方式を決めてから Sonnet | ブラウザ差・タイミングの落とし穴が多い |

### 4.2 タスクの切り方

- **1 PR = 1 つの番号付きタスク**（上の 1-1, 1-2 …）。PR は draft で作り、受け入れ条件を PR 本文に貼る。
- プロンプトの型：

```
docs/PLAN.md の Phase 1 タスク 3「プラン解決」を実装してください。
- 触ってよいファイル：src/08m_media_plan.js（新規）、src/08_planner.js（J.plan の末尾に 1 行のフックのみ）
- 守ること：CLAUDE.md の全項目。決定論（同じ project → 同じ plan.media）。
- 完了条件：python3 build.py 成功、tools/check_page_js.py index.html 成功、dev/test.html で T.setup() 後に plan.media.back.cuts が期待通り。
- 終わったら変更点と確認方法を PR 本文にまとめてください。
```

- レビューの型（Opus）：「この PR を `docs/PLAN.md` §2 と `CLAUDE.md` に照らしてレビュー。特に (1) 本家との差分が最小か (2) 決定論が保たれているか (3) `mergeProject` の検証を通っているか (4) 毎フレームの割り当てが増えていないか」

### 4.3 upstream 追従の手順（月 1 回程度）

```
git fetch upstream
git merge upstream/main          # 衝突は src/09_render.js, src/12_ui.js, app/body.html のフック行に集中するはず
python3 build.py && python3 tools/check_page_js.py index.html
python3 dev/build_test.py all --all-packs && python3 dev/smoke_all.py t_all
```

フック行が最小限であるほど衝突が小さい。**新機能は必ず `08m_*.js` / `11z_*.js` に置き、本家ファイルには「呼び出し 1 行」だけ**を原則にする。

---

## 5. リスクと対策

| リスク | 対策 |
|---|---|
| 動画の seek が遅い／不正確でフレームがズレる・書き出しが数倍遅くなる | `requestVideoFrameCallback` 待ち。長尺は書き出し前に「動画の総フレーム数×seek 時間」の見積もりを出す。Phase 3 以降で WebCodecs デコードに置き換え可能な構造にしておく（`prepareFrame` の裏側だけ差し替え） |
| ブラウザのメモリ（4K 画像 × 多数、動画数本） | ImageBitmap を出力解像度に合わせて縮小して保持（最大辺 = 出力の 1.5 倍）。video は 2 本まで同時保持 |
| Safari / iOS の IndexedDB 容量・`VideoEncoder` 差 | 合計サイズを表示、500MB で警告。iOS は静止画のみ推奨と案内 |
| HEVC / ProRes / 可変フレームレートの素材 | 読み込み時に判定して「H.264 MP4 に変換してください」。ffmpeg のコマンド例を README に載せる |
| 本家との衝突 | §4.3。フック行は `if (J.media)` ガードで囲み、本家側が構造を変えたときに気付きやすくする |
| 歌詞が写真に埋もれて読めない | scrim（§2.3）、`treat:'match'`、`lyricBg:'off'` の組み合わせ。おまかせ側で「メディアあり区間は縁取り／板付きの加工を優先」 |
| 素材の権利 | 自分用なので運用で。README に注意書き |
