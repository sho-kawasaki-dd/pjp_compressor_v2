## Plan: TkinterアプリのFE/BE分離再設計（DRAFT）

現状は [ui_tkinter.py](ui_tkinter.py) がUI・起動副作用・ジョブ組み立てを持ち、[compressor_utils.py](compressor_utils.py) がドメイン処理とI/Oオーケストレーションを混在しており、境界が広く不安定です。確認済みの方針（劣化起動許容／構造化イベント／段階移行／将来UI対応）に合わせ、まず「互換維持しつつ内部を分離」する段階移行を採用します。中核は、UI非依存のアプリケーション層を新設し、`CompressionRequest` と `ProgressEvent` を境界契約として固定化することです。これにより、Tkinterは表示と入力に専念し、将来のPySide6/CLIへ同一バックエンドを再利用できます。

**Steps**

1. 境界契約を定義: 新規 [backend/contracts.py](backend/contracts.py) に `CompressionRequest`、`CapabilityReport`、`ProgressEvent`、`CompressionResult` を集約し、現行 [ui_tkinter.py](ui_tkinter.py) と [compressor_utils.py](compressor_utils.py) 間の引数群をDTO化する。
2. 依存検出を集約: 新規 [backend/capabilities.py](backend/capabilities.py) で `fitz/pikepdf/ghostscript/pngquant` 可用性を判定し、未導入時は機能単位で無効化（劣化起動）する。
3. バックエンドを役割分割: [compressor_utils.py](compressor_utils.py) を `backend/services/pdf_service.py`、`backend/services/image_service.py`、`backend/services/archive_service.py`、`backend/services/cleanup_service.py`、`backend/orchestrator/job_runner.py` に段階分解する。
4. 互換ファサードを維持: [compressor_utils.py](compressor_utils.py) は当面 `compress_folder` 互換APIだけを残し、内部で `job_runner` を呼ぶ薄いアダプタに縮小する（既存UIを壊さない）。
5. UI副作用を排除: [ui_tkinter.py](ui_tkinter.py) の import時処理（初期フォルダ作成・デスクトップ確認・ミキサ初期化）を `App.__init__` 内の明示的起動フローへ移し、モジュールimportを純粋化する。
6. UIをアダプタ化: [ui_tkinter.py](ui_tkinter.py) の `start_compress` はDTO生成＋イベント購読のみにし、`ProgressEvent` を `after()` 経由で描画へ変換する。
7. 起動責務を分離: [compressor_launcher_tkinter.py](compressor_launcher_tkinter.py) は例外ハンドリングとアプリ起動のみを保持し、新規 `app/bootstrap.py` へ設定ロード・能力評価・初期化順序を移す。
8. サウンド境界を整理: [sound_utils.py](sound_utils.py) からGUIダイアログ依存を外し、通知表示はUI層で実施。`init_mixer` は結果を返す純粋APIへ変更する。
9. ドキュメント/配布更新: [Documentation/README.md](Documentation/README.md) と [Documentation/flow_sequence_and_class_diagrams.md](Documentation/flow_sequence_and_class_diagrams.md) を新構成に同期し、[compressor_launcher_tkinter.spec](compressor_launcher_tkinter.spec) のモジュール分割影響（hiddenimports/data）を反映する。

**Verification**

- 単体確認: `backend/contracts.py` のDTO生成、`capabilities` の依存有無分岐、`job_runner` のイベント順序をテスト。
- 結合確認: Tkinterで「通常圧縮」「PDF依存欠落時」「Ghostscript未導入時」の3シナリオを実行し、起動継続と機能無効化通知を確認。
- 回帰確認: 既存の入力/出力フォルダ運用、CSVログ、進捗表示、完了音が現行同等であることを手動比較。
- 配布確認: PyInstallerビルド後にクリーン環境で起動し、欠落依存時にクラッシュしないことを確認。

**Decisions**

- 依存戦略: 起動は継続し、機能単位の劣化で運用継続。
- 境界契約: 文字列コールバックを廃止し、`ProgressEvent` ベースに統一。
- 移行戦略: 互換ファサードを残す段階移行でリスク最小化。
- 将来拡張: Tkinter専用に閉じず、UI非依存バックエンドを前提に設計。

このドラフトを基準に、次の担当エージェントへそのまま実装ハンドオフできる状態です。
