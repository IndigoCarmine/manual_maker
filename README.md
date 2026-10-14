# manual_maker

普段どおりアプリを操作するだけで、操作マニュアル（PDF）を作るヘルパー。

1. **記録** — クリックごとに自動でスクリーンショット（＋ホットキーで手動撮影）
2. **説明生成** — Claude Code (`claude -p`) が画像を見て各手順のタイトル・説明文を書く
3. **修正** — ローカル Web UI で文言修正・並べ替え・削除・クリック位置の調整
   - **Claude で再構成** — 補足に書いたメモ・指示（「不要」「次とまとめる」「ここの説明を足して」等）と全体指示をもとに、
     不要手順の除外・章分け・文章の書き直しを一括で行う（実行前の状態に戻せる）
4. **PDF化** — Typst でレイアウト（表紙・目次・章・手順番号・クリック位置の赤丸）。編集用の `manual.typ` も出力

## 必要なもの
- Windows 10/11
- [uv](https://docs.astral.sh/uv/)、[Typst](https://typst.app/)（`winget install Typst.Typst`）
- Claude Code CLI（`claude` にログイン済みであること）

```
uv sync
```

## 使い方

```powershell
# 1) 記録開始（projects/<名前>/ に保存。既存なら追記）
uv run manual-maker record 経費申請
#   クリック       : 自動撮影（押した瞬間の画面）
#   Ctrl+Shift+S   : 手動撮影（ホバー表示など）
#   Ctrl+Shift+P   : 一時停止 / 再開（パスワード入力時など）
#   Ctrl+Shift+Q   : 終了

# 2) 説明文を生成
uv run manual-maker describe 経費申請 [--model sonnet] [--steps 0003,0005] [--force]

# 3) 編集 UI（http://127.0.0.1:8765）— 記録・生成・PDF作成もここから可能
uv run manual-maker edit 経費申請

# 3') 補足・指示をもとに再構成（実行前の状態は backups/ に保存）
uv run manual-maker restructure 経費申請 -i "GPU設定の手順は省く。初心者向けに丁寧に"
uv run manual-maker undo 経費申請          # 直前の再構成を取り消す

# 4) PDF 作成 → projects/経費申請/manual.typ（編集用）と manual.pdf
uv run manual-maker build 経費申請
```

### Typst ファイルを直接編集する
`build` すると `projects/<名前>/manual.typ`（本文）と `style.typ`（デザイン）が出力されます。
これらは単独でコンパイルできるので、細かい調整は直接編集してください。

```powershell
cd projects\経費申請
typst watch manual.typ               # 保存するたびに manual.pdf を更新
uv run manual-maker compile 経費申請   # 編集した manual.typ をそのまま PDF 化（再生成しない）
```

> `build` や編集UIの「PDF作成」を実行すると `manual.typ` は manual.json から**再生成**されます。
> 手で編集した内容が変わっていた場合は `backups/` に退避されます。手編集を始めたら `compile` / `typst watch` を使ってください。

### 記録のオプション
- `--fullscreen` : ウィンドウではなくモニター全体を撮影
- `--no-keys` : キーボード入力を記録しない（既定では入力文字を次の説明生成のヒントに使う）

### 編集 UI でできること
- 手順のタイトル・説明・補足の編集（自動保存）
- ドラッグ / ↑↓ で並べ替え、PDF から除外、削除
- 画像クリックで強調マーカー位置を変更、強調の ON/OFF
- 「このステップを再生成」「Claudeで説明生成」「PDF作成」→ PDF プレビュー
- 手で編集した文は、全体生成で上書きされない（「編集済みも上書き」をチェックすると上書き）

## 構成
```
src/manual_maker/
  cli.py        コマンド入口
  recorder.py   マウス/キーボードフック・撮影・UI要素名取得（UI Automation）
  winutil.py    Win32 ヘルパー（DPI・ウィンドウ情報・PrintWindow）
  describe.py   claude -p 呼び出し（JSON Schema で構造化出力）
  build.py      typst compile 呼び出し
  server.py     編集 UI の API（FastAPI）
  static/       編集 UI（素の HTML/JS）
  restructure.py 補足・指示をもとにした再構成
templates/style.typ    PDF デザイン（全プロジェクト共通。build 時に各プロジェクトへコピー）
projects/<名前>/        manual.json + images/ + manual.typ + style.typ + manual.pdf + backups/
```

## 注意
- 撮影画像には画面に映っているものがそのまま入ります。個人情報が映る操作は Ctrl+Shift+P で一時停止してください。
- 日本語 IME で確定した文字はキー記録に正しく残らないことがあります（説明生成のヒント用途のみ）。
- 背面のウィンドウをクリックした場合は、重なった他ウィンドウが写らないよう PrintWindow でウィンドウ単体を取得します（一部アプリでは黒くなることがあります）。
