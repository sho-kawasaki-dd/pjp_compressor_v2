**Plan**

GUI の出力設定にアプリ全体のデバッグフラグを追加し、その値を既存の request → orchestrator → worker → PDF 圧縮の流れで伝搬します。今回のスコープでは圧縮ロジック自体は変えず、PyMuPDF ベースの非可逆圧縮でだけ debug stats を標準出力へ出す設計にします。将来の再利用性を確保するため、UI と request では汎用フラグとして保持し、[backend/core/pdf_utils.py](backend/core/pdf_utils.py#L39) の compress_pdf_lossy では提示された debug 引数付きの形に寄せます。

1. 契約追加。 [frontend/ui_tkinter_state.py](frontend/ui_tkinter_state.py#L14) に新しい BooleanVar を追加し、[frontend/ui_contracts.py](frontend/ui_contracts.py#L16) の Protocol と [backend/contracts.py](backend/contracts.py#L56) の CompressionRequest に同じ意味の真偽値フィールドを追加します。命名は debug_mode を推奨します。
2. GUI トグル追加。 [frontend/ui_tkinter_view.py](frontend/ui_tkinter_view.py#L523) の出力設定セクションへ「デバッグモードで出力」のチェックボックスを追加します。CSV、ZIP 展開、ミラーコピーと同じ配置パターンに合わせます。
3. Request 反映。 [frontend/ui_tkinter_mapper.py](frontend/ui_tkinter_mapper.py#L73) の build_compression_request で UI の値を CompressionRequest に載せます。
4. 実行経路反映。 [backend/orchestrator/job_runner.py](backend/orchestrator/job_runner.py#L34) の run_compression_job と [backend/orchestrator/job_runner.py](backend/orchestrator/job_runner.py#L322) の run_compression_request に新フラグを追加し、worker task tuple に積みます。
5. Worker 伝搬。 [backend/core/worker_ops.py](backend/core/worker_ops.py#L10) の process_single_file で tuple の切り出し位置を更新し、PDF 系呼び出しにだけ debug_mode を渡します。JPG/PNG や対象外コピーの挙動は変更しません。
6. PDF lossy デバッグ差し込み。 [backend/core/pdf_utils.py](backend/core/pdf_utils.py#L39) の compress_pdf_lossy に debug=False を追加し、提示された debug_stats と debug_rows の収集を既存の処理順を崩さず組み込みます。print は if debug のときだけ実行し、戻り値と圧縮判定条件は維持します。
7. 上位 PDF 関数の扱い。 [backend/core/pdf_utils.py](backend/core/pdf_utils.py#L287) の compress_pdf_native から lossy 段へだけ debug を渡します。both モードでも lossy 段にだけ効かせます。lossless と Ghostscript 系は今回 no-op のまま据え置くのが最小変更です。
8. Documentation 配下のドキュメント更新。 [Documentation/README.md](Documentation/README.md) に「デバッグモードで出力」トグルの目的と、PyMuPDF 非可逆圧縮時のみ標準出力へ詳細 stats を出す仕様を追記します。加えて [Documentation/flow_sequence_and_class_diagrams.md](Documentation/flow_sequence_and_class_diagrams.md) にも、UI state / CompressionRequest / PDF native lossy 経路へ debug_mode が流れることを反映します。HTML 版を運用上同期しているなら生成物も更新対象に含めます。
9. 検証。 UI 表示、request 反映、native lossy と both での標準出力差分、Ghostscript 経路と画像圧縮経路の非回帰、UI ログタブへ debug 出力が混入しないことを確認します。さらに Documentation の記述が実装と矛盾しないこと、必要なら HTML 生成物も同期されていることを確認します。

**Relevant Files**

- [backend/core/pdf_utils.py](backend/core/pdf_utils.py)
- [backend/core/worker_ops.py](backend/core/worker_ops.py)
- [backend/orchestrator/job_runner.py](backend/orchestrator/job_runner.py)
- [backend/contracts.py](backend/contracts.py)
- [frontend/ui_tkinter_state.py](frontend/ui_tkinter_state.py)
- [frontend/ui_contracts.py](frontend/ui_contracts.py)
- [frontend/ui_tkinter_mapper.py](frontend/ui_tkinter_mapper.py)
- [frontend/ui_tkinter_view.py](frontend/ui_tkinter_view.py)
- [shared/configs.py](shared/configs.py)
- [Documentation/README.md](Documentation/README.md)
- [Documentation/flow_sequence_and_class_diagrams.md](Documentation/flow_sequence_and_class_diagrams.md)
- [Documentation/README.html](Documentation/README.html)
- [Documentation/flow_sequence_and_class_diagrams.html](Documentation/flow_sequence_and_class_diagrams.html)

**Decisions**

- スコープは「アプリ全体にデバッグフラグを追加するが、今回実際に使うのは compress_pdf_lossy の標準出力だけ」に限定します。
- 圧縮ロジック、サイズ比較条件、戻り値メッセージ、GUI ログ仕様は変更しません。
- debug 出力は ProgressEvent に流さず標準出力専用にして、ログタブと CSV を汚さない方針にします。
- 既定値は False。共有定数化は任意ですが、最小差分なら state 側で直接 False 初期化でも十分です。
- Documentation は Markdown を正本として更新し、HTML をリポジトリで管理している運用なら生成物も追随させます。

この計画は /memories/session/plan.md に保存済みです。必要なら次に、1. この方針で実装担当向けにさらに細かい作業順へ分解する 2. そのまま実装へ引き継げる粒度として確定する、のどちらかに進めます。
