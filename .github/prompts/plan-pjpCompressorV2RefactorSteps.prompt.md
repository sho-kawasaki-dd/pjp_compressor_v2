## Plan: FE/BE分離を段階実施（分割版 DRAFT）

**Phase 1: 土台づくり（契約前の安全化）**

1. import時副作用を隔離し、[ui_tkinter.py](ui_tkinter.py) の初期化処理を起動フロー側へ寄せる準備を行う。
2. 既存APIの互換維持ポイントを明確化し、[compressor_utils.py](compressor_utils.py) を将来ファサード化できる形に整理する。
3. 完了条件: 現行UIで既存フローが壊れていないことを確認。

**Phase 2: 境界契約の固定化**

1. [backend/contracts.py](backend/contracts.py) を新設し、Request/Event/ResultのDTOを定義する。
2. [backend/capabilities.py](backend/capabilities.py) を新設し、依存欠落時の劣化起動ルールを統一する。
3. 完了条件: UIとBEの受け渡し仕様が文字列コールバック依存から契約中心に移行可能な状態になる。

**Phase 3: バックエンド分割（内部再編）**

1. [compressor_utils.py](compressor_utils.py) の責務を services と orchestrator に分解する。
2. 分割先は [backend/services/pdf_service.py](backend/services/pdf_service.py)、[backend/services/image_service.py](backend/services/image_service.py)、[backend/services/archive_service.py](backend/services/archive_service.py)、[backend/services/cleanup_service.py](backend/services/cleanup_service.py)、[backend/orchestrator/job_runner.py](backend/orchestrator/job_runner.py)。
3. 完了条件: 既存機能が job_runner 経由で実行できること。

**Phase 4: 互換ファサード + UI接続**

1. [compressor_utils.py](compressor_utils.py) を薄い互換ファサード化し、既存呼び出しを維持しつつ内部を新構成へ委譲する。
2. [ui_tkinter.py](ui_tkinter.py) の start_compress を DTO生成 + イベント購読に限定する。
3. 完了条件: UIの見た目・操作感を保ったまま、新BE境界で正常圧縮できること。

**Phase 5: 起動・サウンド責務の分離**

1. [compressor_launcher_tkinter.py](compressor_launcher_tkinter.py) を薄いエントリポイント化し、起動順序は [app/bootstrap.py](app/bootstrap.py) に集約する。
2. [sound_utils.py](sound_utils.py) のGUI依存を除去し、通知表示責務をUI側へ戻す。
3. 完了条件: 起動時クラッシュ低減と責務分離が確認できること。

**Phase 6: ドキュメント・配布反映**

1. 新構成へ [Documentation/README.md](Documentation/README.md) と [Documentation/flow_sequence_and_class_diagrams.md](Documentation/flow_sequence_and_class_diagrams.md) を同期する。
2. [compressor_launcher_tkinter.spec](compressor_launcher_tkinter.spec) を更新し、分割後モジュールの配布要件を反映する。
3. 完了条件: クリーン環境での起動と欠落依存時の劣化動作が確認できること。

この分割版なら、各フェーズ単位でレビュー・ロールバックしながら安全に進められます。
