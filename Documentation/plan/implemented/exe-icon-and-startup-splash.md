## Plan: EXE Icon And Startup Splash

`images/pjp_compressor_icon.ico` を PyInstaller の実行ファイルアイコンに設定し、Tkinter 起動時に `images/pjp_compressor_splash.png` を原寸表示するスプラッシュを追加する。方式は「Tkinter側実装（Python実行時も表示）」、終了条件は「メイン画面表示と同時に閉じる」。既存のリソース解決ロジック（`RESOURCE_BASE_DIR`）を再利用して、通常実行と凍結実行の両方で動作させる。

**Steps**
1. Phase 1: Build artifact icon 設定
2. `c:\Users\tohbo\python_programs\pjp_compressor_v2\compressor_launcher_tkinter.spec` の `EXE(...)` に `icon='images/pjp_compressor_icon.ico'` を追加する。依存: なし。
3. 必要に応じて `Analysis(...).datas` の取り扱いを確認し、`images` を同梱対象に追加する（PyInstaller実行後の `dist` で splash 画像が解決されることを優先）。依存: step 2。
4. Phase 2: 共有設定のリソース経路追加
5. `c:\Users\tohbo\python_programs\pjp_compressor_v2\shared\configs.py` に `IMAGES_DIR = os.path.join(RESOURCE_BASE_DIR, 'images')` を追加し、通常実行・凍結実行の両方で同一参照できる定数として公開する。依存: なし（step 6 と並行可能）。
6. Phase 3: Tkinter スプラッシュ実装
7. `c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\bootstrap.py` にスプラッシュ表示ヘルパーを実装する。`run_tkinter_app()` で `App()` 生成直後にスプラッシュ `Toplevel` を表示し、`pjp_compressor_splash.png` を `PhotoImage` で原寸描画する。依存: step 5。
8. メイン画面表示と同時に閉じる要件に合わせ、`run_tkinter_app()` の初期化順を調整する。具体的にはメインウィンドウを一時的に非表示で初期化し、スプラッシュの描画完了後にメインウィンドウを表示して即座にスプラッシュを破棄する。依存: step 7。
9. 画像読み込み失敗時（ファイル欠落、対応形式不一致）はスプラッシュをスキップして通常起動を継続するフォールバックを追加する。依存: step 7。
10. Phase 4: アプリウィンドウアイコン適用
11. `c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\ui_tkinter.py` の `App.__init__()` 初期段階でウィンドウアイコン設定を追加する（`iconbitmap` を優先し、失敗時は無害に継続）。依存: step 5。
12. Phase 5: 動作確認
13. ローカル Python 実行で、起動時にスプラッシュ（原寸）が表示され、メイン画面表示と同時に閉じることを確認する。依存: steps 7-9。
14. PyInstaller ビルド（既存 `compressor_launcher.ps1`）後、生成 exe のファイルアイコンが `pjp_compressor_icon.ico` になっていることをエクスプローラーで確認する。依存: steps 2-3。
15. 生成 exe 起動で、スプラッシュ画像の表示とアプリ起動継続（例外なし）を確認する。依存: steps 7-11,14。

**Relevant files**
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\compressor_launcher_tkinter.spec` — `EXE(...)` への `icon` 追加、必要なら `datas` へ `images` 同梱追加。
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\shared\configs.py` — `IMAGES_DIR` 定数追加（`RESOURCE_BASE_DIR` 再利用）。
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\bootstrap.py` — `run_tkinter_app()` の起動順制御とスプラッシュ表示/破棄処理。
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\frontend\ui_tkinter.py` — `App.__init__()` でウィンドウアイコン設定。
- `c:\Users\tohbo\python_programs\pjp_compressor_v2\compressor_launcher.ps1` — 既存ビルド導線（変更不要、検証時に利用）。

**Verification**
1. `python compressor_launcher_tkinter.py` 実行で、スプラッシュが起動直後に原寸表示され、メイン画面表示時に消えることを目視確認。
2. 起動ログ/標準エラーに例外が出ないことを確認（画像欠落時は警告のみまたは無音フォールバック）。
3. `compressor_launcher.ps1` でビルドし、`dist` 配下の exe のプロパティまたはエクスプローラー表示でアイコン反映を確認。
4. 生成 exe を実行し、スプラッシュ表示と通常操作（フォルダ選択、終了処理）が回帰していないことを確認。

**Decisions**
- 採用方式: Tkinter 側スプラッシュ（PyInstaller boot splash は不採用）。
- スプラッシュ終了条件: メイン画面表示と同時に閉じる。
- 画像サイズ: `pjp_compressor_splash.png` を原寸表示。
- In scope: exe アイコン設定、起動時スプラッシュ表示、通常/凍結実行のリソース解決。
- Out of scope: スプラッシュ演出追加（フェード等）、ロード進捗バー、画像デザイン変更。

**Further Considerations**
1. `PhotoImage` の PNG 対応差異がある環境向けに `Pillow` フォールバックを追加するか。推奨: 現在依存を増やさず標準 `PhotoImage` で開始し、必要時のみ追加。
2. スプラッシュを多重起動させないガード（将来再起動機能追加時）を入れるか。推奨: 初回はシンプル実装、要件化時に拡張。
