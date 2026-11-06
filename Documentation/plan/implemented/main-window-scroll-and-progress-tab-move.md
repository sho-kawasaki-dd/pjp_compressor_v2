## Plan: Main Window Scroll + Progress Tab Move

低解像度ディスプレイでも `実行/終了` ボタンへ到達できるよう、Tk ルート直下を `Canvas + 縦スクロールバー` のスクロールコンテナ化し、既存の全セクション（フォルダ行、Notebook、ボタン行）をその内部へ移します。あわせて進捗表示を独立セクションからログタブへ移設し、進捗更新ロジックは既存の `self.progress` / `self.status_var` 参照を維持してUI構成のみ変更します。

**Steps**
1. 事前整理: `TkUiViewMixin.build_layout` の構成を `root直下スクロールコンテナ + content_frame` 前提へ再設計し、既存の `pack` 階層を壊さない移行方針を決定する。
2. Phase 1 - 全体スクロール土台を追加（依存なし）
3. `frontend/ui_tkinter_view.py` にルート用スクロールコンテナ生成メソッド（例: `_build_root_scroll_container`）を追加し、`self` 直下に `Canvas` と縦 `ttk.Scrollbar`、`canvas.create_window` で `self.main_container` を作る。
4. `frontend/ui_tkinter_view.py` の `build_layout` を更新し、既存の `_build_folder_section` / `_build_notebook` / `_build_progress_section` / `_build_action_buttons` 呼び出し先親を `self.main_container` 側に切り替える（`_build_progress_section` は後続Phaseで削除）。
5. `frontend/ui_tkinter_view.py` で `main_container` の `<Configure>` と Canvas 幅同期（Canvas幅変更時に内部window幅を追従）を実装し、縦スクロール領域を自動更新する。
6. `frontend/ui_tkinter.py` でマウスホイール連携を初期化し、Windows前提の `<MouseWheel>` でルートCanvasをスクロールできるようにする。Notebook内の `Text` など既存スクロールと競合しないよう、フォーカス/ポインタ位置に応じたイベント伝播方針を適用する。
7. Phase 2 - 進捗バーをログタブへ移動（depends on 2-6）
8. `frontend/ui_tkinter_view.py` の `build_layout` から `_build_progress_section` 呼び出しを削除し、`_build_progress_section` メソッドは削除または非使用化する。
9. `frontend/ui_tkinter_view.py` の `_build_log_tab` を拡張し、`stats_frame` の直下に進捗UI（状態ラベル + `self.progress`）を挿入する。既存 `self.status_var` と `self.progress` 名称は維持し、`TkUiControllerMixin` の更新処理変更を不要にする。
10. Phase 3 - レイアウト調整と回帰対策（depends on 8-9）
11. ログタブ内の縦方向配分を調整し、進捗UI追加後も `log_text` が `fill='both', expand=True` で十分な表示領域を保つよう `pady`/`height` を微調整する。
12. `auto_switch_log_tab` がONの既存挙動（`start_compress` で `self.notebook.select(self.log_tab)`）で、圧縮開始時に進捗UIが確実に見えることを確認する。
13. スクロール時のUX最終調整: 全体スクロールが有効な状態で、ログテキストスクロールバー操作時に意図しない全体スクロールが起きないようイベントバインドの優先度を点検する。

**Relevant files**
- `c:/Users/tohbo/python_programs/pjp_compressor_v2/frontend/ui_tkinter_view.py` — `build_layout`, `_build_notebook`, `_build_log_tab`, `_build_action_buttons` の親コンテナ変更、ルートスクロールコンテナ追加、進捗セクション移設。
- `c:/Users/tohbo/python_programs/pjp_compressor_v2/frontend/ui_tkinter.py` — `App.__init__` で全体スクロール用マウスホイール初期化（必要なイベントバインド）を追加。
- `c:/Users/tohbo/python_programs/pjp_compressor_v2/frontend/ui_tkinter_controller.py` — 原則変更なし（`_update_progress_ui`, `update_progress`, `start_compress` の参照整合を確認のみ）。

**Verification**
1. 低解像度検証: 800x600 相当で起動し、画面下部が切れても全体スクロールで `圧縮開始` / `終了` ボタンまで到達できることを確認。
2. 進捗表示位置: ログタブ内に状態表示と進捗バーが表示され、独立進捗セクションがメイン画面から消えていることを確認。
3. 進捗更新: 圧縮実行中に `self.progress['value']` と `self.status_var` が従来通り更新されることを確認（回帰なし）。
4. タブ連携: `圧縮開始時にログタブへ自動切替` ONで開始したとき、ログタブが前面化し進捗バーが見えることを確認。
5. スクロール競合: ログタブの `Text` スクロールと全体スクロールが過剰干渉しないことを確認（ホイールで操作対象が自然であること）。
6. リサイズ耐性: ウィンドウ拡大/縮小時にCanvas内部幅追従が崩れず、横レイアウトが欠けないことを確認。

**Decisions**
- スクロール範囲はユーザー回答に基づき `A: ウィンドウ全体` を採用。
- 進捗バーはログタブへ一本化し、メイン画面の専用進捗セクションは廃止。
- Controller層の進捗更新ロジックは変更せず、View層のウィジェット配置のみ変更して影響範囲を最小化。

**Further Considerations**
1. 全体スクロール時のホイール優先度: Option A `常に全体スクロール優先` / Option B `Text上はText優先（推奨）` / Option C `Shift+Wheelで全体スクロール`。
2. 将来保守性: ルートスクロール化後、設定項目が増えてもUI崩れしにくいよう「親フレームは `self.main_container` に pack」の規約をコメントで明示する.
