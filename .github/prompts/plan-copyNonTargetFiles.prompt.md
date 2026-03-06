## Plan: 対象外ファイルコピーオプション追加

入力フォルダの相対構造を維持しつつ、未対応拡張子のみを出力へコピーするトグル（既定OFF）を追加し、UI→Request→JobRunnerまで値を伝播する計画です。要件確認済みの通り、圧縮失敗時は対象拡張子でも元ファイルをフォールバックコピーします。

**Steps**
1. `shared/configs.py` に既定値定数（例: `COPY_NON_TARGET_FILES_DEFAULT = False`）を追加して、既定OFFを一元化。
2. `frontend/ui_tkinter_state.py` の `initialize_ui_state()` に新しい `BooleanVar` を追加し、Step 1 の定数を初期値に設定。
3. `frontend/ui_tkinter_view.py` の `_build_output_section` に出力設定トグルを追加（既存レイアウトに合わせる）。
4. `backend/contracts.py` の `CompressionRequest` に新規 bool フィールドを追加。
5. `frontend/ui_tkinter_mapper.py` の `build_compression_request()` でトグル値を `CompressionRequest` にマップ。  
   依存: Step 4
6. `backend/orchestrator/job_runner.py` の `run_compression_job()` で新規引数を受け取る。  
   依存: Step 4
7. `backend/orchestrator/job_runner.py` にコピー処理を追加。内容:
   - 圧縮対象拡張子（`pdf/jpg/jpeg/png`）を明示。
   - トグルON時、未対応拡張子を `input_base` からの相対パスで `output_base` にコピー。
   - 圧縮対象でも `processed=False` の場合はフォールバックコピー。
   - コピー前に出力ディレクトリを `mkdir(parents=True, exist_ok=True)` で保証。
8. 同ファイルでログを追加し、以下を区別して出力:
   - 対象外ファイルコピー
   - 圧縮失敗フォールバックコピー
   - コピー失敗例外
9. 回帰と機能検証を実施（OFF時挙動維持、ON時コピー、失敗時フォールバック、既存圧縮/ZIP展開維持）。

**Relevant files**
- `c:/Users/tohbo/python_programs/pjp_compressor_v2/shared/configs.py`
- `c:/Users/tohbo/python_programs/pjp_compressor_v2/frontend/ui_tkinter_state.py`
- `c:/Users/tohbo/python_programs/pjp_compressor_v2/frontend/ui_tkinter_view.py`
- `c:/Users/tohbo/python_programs/pjp_compressor_v2/frontend/ui_tkinter_mapper.py`
- `c:/Users/tohbo/python_programs/pjp_compressor_v2/backend/contracts.py`
- `c:/Users/tohbo/python_programs/pjp_compressor_v2/backend/orchestrator/job_runner.py`
- `c:/Users/tohbo/python_programs/pjp_compressor_v2/backend/core/worker_ops.py`（失敗判定の参照）

**Verification**
1. UIで新トグルが表示され、初期値OFFであること。
2. OFF時に未対応拡張子が出力へコピーされないこと。
3. ON時に未対応拡張子が相対構造を維持してコピーされること。
4. ON時に圧縮失敗ファイルがフォールバックコピーされること。
5. ログで3種（通常コピー/フォールバック/失敗）が判別できること。
6. 既存の `pdf/jpg/jpeg/png` 圧縮とZIP展開が回帰していないこと。

**Decisions**
- 「圧縮対象外」は未対応拡張子（`pdf/jpg/jpeg/png` 以外）。
- 圧縮対象でも失敗時はコピーする。
- トグル既定値はOFF。
- スコープ内: UIトグル、値伝播、コピー処理、ログ。
- スコープ外: 空ディレクトリ明示作成、リネーム衝突解消、CSV仕様変更。
