# Plan: UI 多言語対応（日本語/English）

**TL;DR**: `frontend/i18n.py` を新設して全表示文字列を `t('key')` 経由に統一。翻訳文字列は `frontend/config_data/locales/ja.json` / `en.json` で管理。言語設定は既存の `ui_catalogs.json` の `app_settings.language` に保存し、**次回起動時に反映**。

---

## Phase 1: i18n インフラ（並列可）

1. **`frontend/i18n.py`** 新規作成
   - `detect_os_language() -> str` — `locale.getdefaultlocale()` で ja 系 → `'ja'`、それ以外 → `'en'`
   - `init_from_settings(resource_path=None) -> str` — `ui_catalogs.json` から `language` を読み、空なら OS 検出 → `load()` 呼び出し → 使用言語を返す
   - `load(language: str) -> None` — ロケール JSON を `_current` dict にキャッシュ
   - `t(key: str, **kwargs) -> str` — `_current.get(key, key).format(**kwargs)` （キー未登録ならキー自体を返す安全フォールバック）

2. **`frontend/config_data/locales/ja.json`** 新規作成 — 全 UI 表示文字列（日本語）

3. **`frontend/config_data/locales/en.json`** 新規作成 — 全 UI 表示文字列（英語）

> ロケール JSON のキー群（抜粋）: `app_title`, `label_input_folder`, `btn_select`, `btn_cleanup`, `tab_settings`, `tab_log`, `pdf_mode.lossy`, `gs_preset.ebook`, `status_processing`, `stats_summary`, `log_compress_start`, `dlg_cleanup_input_msg`, `desktop_input_folder`, `tool_source.unavailable`, ...（全 ~80 キー程度）

---

## Phase 2: 設定レイヤ変更（Phase 1 と並列可）

4. **`frontend/settings.py`** 変更
   - `APP_SETTINGS_DEFAULTS` に `'language': ''`（空 = 自動検出）追加
   - `load_app_settings()` / `save_app_settings()` に `language` パラメータ追加
   - `PDF_COMPRESS_MODES`, `GS_PRESETS` モジュール定数を**削除**（表示ラベルはロケール JSON へ移動）
   - `_load_ui_catalogs()` は `long_edge_presets` のみ返すよう縮小

5. **`frontend/config_data/ui_catalogs.json`** 変更
   - `pdf_compress_modes`, `gs_presets` キー削除
   - `app_settings` に `"language": ""` 追加

6. **`shared/configs.py`** — `GS_PRESETS`, `PDF_COMPRESS_MODES` の import / re-export 削除

7. **`shared/runtime_paths.py`** — `TOOL_SOURCE_LABELS['unavailable']` を `'未検出'` → `'unavailable'` に変更（i18n 依存を shared に持ち込まない）

---

## Phase 3: UI 文字列置換（Phase 1・2 完了後）

8. **`frontend/bootstrap.py`** — `App()` 生成前に `i18n.init_from_settings()` を呼び出す（全 `t()` 呼び出しより先に初期化）

9. **`frontend/ui_tkinter_view.py`** — `GS_PRESETS`/`PDF_COMPRESS_MODES` import 削除、`from frontend.i18n import t` 追加、全 hardcoded 文字列を `t('key')` へ置換

10. **`frontend/ui_tkinter_controller.py`** — `from frontend.i18n import t` 追加、全文字列置換、`describe_tool_source()` 呼び出しを `t(f'tool_source.{source}')` に変更、`_save_app_settings()` に `ui_language` 保存を追加

11. **`frontend/ui_tkinter_state.py`** — `ui_language: tk.StringVar` を `initialize_ui_state()` に追加

12. **`frontend/ui_tkinter.py`** — `get_default_dirs()` のフォルダ名・ダイアログを `t()` 化、ウィンドウタイトル `t('app_title')`

---

## Phase 4: 言語選択 UI（Phase 3 完了後）

13. **`frontend/ui_tkinter_view.py`** の `_build_app_settings_tab()` に言語セクション追加
   - `( ●) 日本語  ( ) English` Radiobutton
   - `"再起動後に反映されます / Will be applied after restart"` ラベル

---

## Phase 5: テスト更新（Phase 1〜4 完了後）

14. **`tests/unit/test_app_settings.py`** — モック JSON から `pdf_compress_modes`/`gs_presets` 削除、`language` キーのテスト追加
15. **`tests/unit/test_settings_split.py`** — `PDF_COMPRESS_MODES`/`GS_PRESETS` re-export テストを削除または更新
16. **`tests/unit/test_i18n.py`** 新規作成（`t()`, `detect_os_language()`, `init_from_settings()` の単体テスト）

---

## 関連ファイル（修正対象）

| ファイル | 変更種別 |
|---|---|
| `frontend/i18n.py` | 新規 |
| `frontend/config_data/locales/ja.json` | 新規 |
| `frontend/config_data/locales/en.json` | 新規 |
| `frontend/settings.py` | 変更 |
| `frontend/config_data/ui_catalogs.json` | 変更 |
| `frontend/ui_tkinter_view.py` | 変更 |
| `frontend/ui_tkinter_controller.py` | 変更 |
| `frontend/ui_tkinter_state.py` | 変更 |
| `frontend/ui_tkinter.py` | 変更 |
| `frontend/bootstrap.py` | 変更 |
| `shared/configs.py` | 変更 |
| `shared/runtime_paths.py` | 変更 |
| `tests/unit/test_app_settings.py` | 変更 |
| `tests/unit/test_settings_split.py` | 変更 |
| `tests/unit/test_i18n.py` | 新規 |

---

## 検証

1. `pytest tests/unit/` で全ユニットテスト通過
2. 起動: OS ロケール `ja_JP` → 日本語 UI が表示される
3. アプリ設定タブで `English` 選択 → 保存 → 再起動 → 英語 UI 表示
4. 英語モードで Desktop フォルダ作成確認 → `"To Compress"` / `"Compressed Files"` 名で作成される
5. 英語モードでクリーンアップ・圧縮実行 → ログ・ダイアログが英語で表示される
6. PyInstaller ビルド後の動作確認（`_MEIPASS` 下のロケールファイルパス解決）

---

## 補足判断事項

- **`GS_PRESETS` / `PDF_COMPRESS_MODES` の削除**について: これらの表示ラベルはビューでのみ使用されており、内部キー（`'lossy'`, `'ebook'` 等）はロケールとは無関係なので安全に分離できます。`shared/configs.py` 経由での再 export も削除対象。
- **ログメッセージ翻訳の実装方針**: コントローラが生成するメッセージ（status, dialog）はすべて `t()` 化。バックエンドが生成するメッセージ（`ProgressEvent.message`）はバックエンドが英語で統一 or 日本語固定のどちらでも可です。現状の日本語メッセージをそのまま継続することを前提にしていますが、変更したい場合は別途検討が必要です。
