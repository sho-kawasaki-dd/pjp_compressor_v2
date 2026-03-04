## Plan: compressor_utils責務分割（DRAFT）

`backend/core` を責務別に分割しつつ、既存利用箇所を壊さない段階移行を行います。今回の決定は「core分割主軸」「互換は広めに維持」「`compress_pdf` は削除前提で呼び出し側更新」「`compressor_utils.py` は shim として残す」です。循環依存の要点は、現在 `job_runner` が遅延 import で `process_single_file` と `human_readable` を参照している点（[backend/orchestrator/job_runner.py](backend/orchestrator/job_runner.py#L38-L46)）なので、ここを先に安定化してから本体を分割します。最終的に、機能配置は PDF・画像・アーカイブ・クリーンアップ・ワーカー・公開APIに分離し、既存 import パスは shim 経由で互換を維持します。

**Steps**

1. 分割先モジュールを新設
   - [backend/core/pdf_utils.py](backend/core/pdf_utils.py), [backend/core/image_utils.py](backend/core/image_utils.py), [backend/core/archive_utils.py](backend/core/archive_utils.py), [backend/core/file_ops.py](backend/core/file_ops.py), [backend/core/worker_ops.py](backend/core/worker_ops.py), [backend/core/format_utils.py](backend/core/format_utils.py) を追加。
   - 既存関数を責務ごとに移設し、シグネチャ・戻り値を完全維持。

2. orchestrator の依存を新モジュールへ切替（循環回避を先に確定）
   - [backend/orchestrator/job_runner.py](backend/orchestrator/job_runner.py) の遅延 import を `format_utils.human_readable` と `worker_ops.process_single_file` に変更。
   - これで `compressor_utils.py` への実行時依存を外し、以降の分割を安全化。

3. services の import を新モジュールへ直接切替
   - [backend/services/archive_service.py](backend/services/archive_service.py) → `archive_utils`。
   - [backend/services/image_service.py](backend/services/image_service.py) → `image_utils`。
   - [backend/services/cleanup_service.py](backend/services/cleanup_service.py) → `file_ops`。
   - [backend/services/pdf_service.py](backend/services/pdf_service.py) は `compress_pdf` を削除し、`pdf_utils` のみを再公開。

4. 公開 API の受け口を再構成
   - [backend/core/compressor_utils.py](backend/core/compressor_utils.py) を shim 化し、外部互換が必要な既存シンボルを再エクスポート。
   - `PUBLIC_BACKEND_API` / `__all__` / `get_public_api_symbols` は維持（`compress_folder`, `cleanup_folder`, `count_target_files`, `human_readable`, `get_ghostscript_path`）。
   - `compress_folder` は従来通り orchestrator 委譲を保持。

5. `compress_pdf` 参照を整理（削除前提方針）
   - `pdf_service` の `compress_pdf` export/import を除去。
   - ワークスペース内で `compress_pdf(` の参照を確認し、残存があれば `compress_pdf_native` へ明示置換。

6. core パッケージの公開整理
   - 必要に応じて [backend/core/**init**.py](backend/core/__init__.py) を更新し、新モジュールの公開方針を明確化。
   - 既存利用者が `backend.core.compressor_utils` を使っても破綻しない状態を維持。

7. ドキュメント最小更新
   - [Documentation/README.md](Documentation/README.md)（または実運用README）に「責務分割後のモジュール配置」と「互換 shim の位置づけ」を追記。

**Verification**

- 静的確認: `python -m compileall backend frontend shared`
- 回帰確認: `python scripts/tkinter_regression_check.py`
- 実行確認: GUI 起動後に PDF/JPG/PNG 圧縮、ZIP展開、入力/出力クリーンアップを各1回実施
- 依存確認: `backend.core.compressor_utils` の import で既存5 APIが取得できることを確認
- 参照確認: ワークスペース検索で `from backend.core.compressor_utils import compress_pdf` が 0 件であることを確認

**Decisions**

- 方針: core分割主軸
- 互換範囲: 広めに維持（shim を残す）
- `compress_pdf`: 削除し、呼び出し側を更新
- 移行方式: 段階移行（即時一斉削除はしない）

このドラフトを基準に、次のターンでそのまま実装フェーズに渡せる粒度まで固めています。
