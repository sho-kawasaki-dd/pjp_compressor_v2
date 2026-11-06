## Plan: ZIP 出力モード追加

ZIP入力を展開して圧縮した後の出力形式を、ZIP由来の成果物に限ってフォルダ/ZIPで切り替えられるようにする。GUI は圧縮タブの出力設定に単一トグルを追加し、backend request 契約から orchestrator まで同じフラグを通す。ZIP出力時は、mirror 圧縮で残す非圧縮対象ファイルも再生成ZIPへ含め、元の入力ZIPは別コピーしない。

**Steps**
1. Request 契約と UI state を拡張する。`backend/contracts.py` の `CompressionRequest` と `to_legacy_kwargs()` に新しい boolean フラグを追加し、`backend/settings.py` に既定値を定義する。`frontend/ui_tkinter_state.py` で Tk 変数を初期化し、`frontend/ui_tkinter_mapper.py` の `build_compression_request()` から request へ流す。
2. 圧縮タブの出力設定 UI に単一トグルを追加する。`frontend/ui_tkinter_view.py` の `_build_output_section()` で `extract_zip` の近傍へ配置し、文言は ZIP入力にだけ効くことが分かる表現にする。通常ファイルの出力仕様は変更しない。
3. ZIP由来の出力管理を orchestrator 側で明示化する。`backend/orchestrator/job_runner.py` の ZIP 展開フェーズで、各 ZIP 入力ごとに最終出力ルートと ZIP 再生成先を追跡できるようにし、現状の `output_base / zip_stem` 直書きだけで終わらない構造へ整理する。
4. ZIP 再生成 helper を追加する。`backend/core/archive_utils.py` に、指定ディレクトリ配下を相対パス維持で ZIP 化する helper を追加する。`job_runner.py` は圧縮完了後、ZIP出力トグルが ON のときだけ ZIP由来の出力フォルダをこの helper で archive 化し、成功後に対応フォルダを削除する。
5. mirror 圧縮との相互作用を整理する。ZIP出力トグルが ON の場合、ZIP入力そのものを `output_dir` へ先行コピーする現在の `zip_output_copies` には入れず、ZIP 内の非圧縮対象ファイルや圧縮失敗ファイルは従来どおり一時展開側から最終成果物へ取り込んで再生成ZIPへ含める。通常ファイルに対する mirror 圧縮の挙動は変えない。
6. ログと CSV の扱いを調整する。CSV の `input_path` は現行どおり `zip::path` 表記を維持し、`output_path` は ZIPモード時だけ最終的な archive パスを表すか、現状の内部パス表現を維持するかを実装内で一貫させる。推奨は既存CSV互換を優先して `zip_stem/internal/path` を残し、ログに「ZIP再生成」を別途出す形に留める。
7. unit / integration / regression テストを拡張する。`tests/unit/test_contracts.py` と `tests/unit/test_ui_tkinter_mapper.py` で新フラグの request 伝搬を固定し、`tests/integration/test_job_runner.py` で ZIP由来出力が folder/zip で切り替わるケース、mirror 併用時に元ZIPを別コピーしないケース、入力不変性を検証する。`tests/regression/test_tkinter_regression.py` の ZIP 行列テストは新トグル軸を追加し、GUI 経由でも期待どおりの成果物になることを確認する。
8. 必要なら controller 系ダミーを最小更新する。`build_compression_request()` を使う `DummyApp` / `DummyMapperApp` へ新 state を追加し、既存テストの request 生成失敗を防ぐ。controller の挙動自体は変えない想定なので、変更は request 生成面に限定する。

**Relevant files**
- `backend/contracts.py` - `CompressionRequest` と `to_legacy_kwargs()` に新フラグを追加する
- `backend/settings.py` - 新フラグの既定値を定義する
- `backend/orchestrator/job_runner.py` - ZIP展開、mirror コピー、最終成果物生成の分岐を実装する中心
- `backend/core/archive_utils.py` - ディレクトリを再ZIP化する helper の追加候補
- `frontend/ui_tkinter_state.py` - Tk 変数の追加
- `frontend/ui_tkinter_view.py` - 圧縮タブの出力設定トグル追加
- `frontend/ui_tkinter_mapper.py` - request へのマッピング追加
- `tests/unit/test_contracts.py` - contract 伝搬の固定
- `tests/unit/test_ui_tkinter_mapper.py` - mapper 伝搬の固定
- `tests/integration/test_job_runner.py` - ZIP出力モードの挙動確認
- `tests/regression/test_tkinter_regression.py` - GUI 経由の ZIP 回帰

**Verification**
1. `pytest tests/unit/test_contracts.py tests/unit/test_ui_tkinter_mapper.py`
2. `pytest tests/integration/test_job_runner.py -k zip`
3. `pytest tests/regression/test_tkinter_regression.py -k zip`
4. 手動で ZIP 展開 ON のまま新トグル OFF/ON を切り替え、同じ ZIP 入力からフォルダ出力と ZIP 出力の両方を確認する
5. 新トグル ON + mirror ON で、再生成ZIP内に txt など非圧縮対象が入り、`output_dir` 直下に元入力ZIPの別コピーが出ないことを確認する

**Decisions**
- 新機能の対象は ZIP入力から展開された成果物のみで、通常ファイル出力は変更しない
- GUI は単一トグルとし、圧縮タブの出力設定内で `extract_zip` の近くに置く
- ZIP出力時は mirror 圧縮由来の非圧縮対象も再生成ZIPへ含める
- ZIP出力時、元の入力ZIPは `output_dir` へ別コピーしない
- スコープ外: ジョブ全体を 1 本の ZIP にまとめる機能、通常ファイル群の一括 ZIP 出力、CSV 形式の大幅刷新

**Further Considerations**
1. トグル文言は誤解を避けるため「展開したZIPの出力をZIPに戻す」のように ZIP入力限定を明記するのが安全
2. CSV の `output_path` は互換性優先で内部パス表現を維持し、必要なら後続タスクで CSV 列追加を別件対応する