## Plan: Tkinter UI責務分割（DRAFT）

現状の [frontend/ui_tkinter.py](frontend/ui_tkinter.py) は、画面生成・状態保持・入力検証・リクエスト組み立て・非同期実行・進捗反映が1クラスに集中しています。合意内容（案A採用、外部互換は必要最小限変更可、README＋設計資料同時更新）に基づき、公開エントリは維持しつつ内部を View / Controller / StateMapper に段階分離します。起動互換性は [frontend/bootstrap.py](frontend/bootstrap.py) と [compressor_launcher_tkinter.py](compressor_launcher_tkinter.py) を壊さないことを優先し、Tkメインスレッド制約と劣化起動（依存欠落時も継続）を明示的に維持します。最終形は既存 App を薄いファサード化し、将来の機能追加時に UI部品・イベント処理・DTO変換を独立改修できる構造にします。

**Steps**

1. 分割用の責務境界を確定し、App内メソッドを3群へマッピングする（View群: build系、Controller群: on/update/start/cleanup系、Mapper群: request生成系）対象: [frontend/ui_tkinter.py](frontend/ui_tkinter.py#L212-L1118)。
2. UI状態を集約する state モジュールを設計し、現在の tk変数定義を移管対象として整理する（PDF/画像/出力/進捗/ログに分類）対象: [frontend/ui_tkinter.py](frontend/ui_tkinter.py#L132-L188)。
3. Viewモジュールを新設し、ウィジェット生成とレイアウトのみを移す（イベント配線は Controller 経由に統一）対象: [frontend/ui_tkinter.py](frontend/ui_tkinter.py#L212-L613)。
4. Controllerモジュールを新設し、入力検証・進捗イベント受信・ジョブ開始/停止・クリーンアップを移す（UI更新は after 経由を維持）対象: [frontend/ui_tkinter.py](frontend/ui_tkinter.py#L665-L1118), [backend/orchestrator/job_runner.py](backend/orchestrator/job_runner.py#L207-L254), [backend/contracts.py](backend/contracts.py#L38-L95)。
5. RequestMapperモジュールを新設し、CompressionRequest 組み立てと関連検証を分離する（設定依存は mapper 側で吸収）対象: [frontend/ui_tkinter.py](frontend/ui_tkinter.py#L934-L1062), [shared/configs.py](shared/configs.py#L85-L101)。
6. 互換レイヤとして [frontend/ui_tkinter.py](frontend/ui_tkinter.py) に App ファサードを残し、外部呼び出し点との接続を再配線する（必要最小限で import 変更）対象: [frontend/bootstrap.py](frontend/bootstrap.py#L6-L14), [compressor_launcher_tkinter.py](compressor_launcher_tkinter.py#L23-L72)。
7. 依存関係を再点検し、循環importとモジュール初期化副作用（DPI設定・DND検出）の順序を固定する。
8. 文書更新を実施し、構成図と起動/責務説明を同期する。対象: [Documentation/README.md](Documentation/README.md), [Documentation/flow_sequence_and_class_diagrams.md](Documentation/flow_sequence_and_class_diagrams.md)。

**Verification**

- 静的確認: 新モジュール間で循環importがないこと、起動時importエラーがないことを確認。
- 起動確認: `compressor_launcher_tkinter.py` と `frontend/bootstrap.py` 経由でGUI起動し、依存欠落時の劣化起動が維持されることを確認。
- 動作確認: フォルダ選択、設定変更、圧縮開始、進捗表示、ログ出力、停止/クリーンアップを一連で確認。
- 回帰確認: D&D有効/無効環境、音再生可否、PDF/画像の主要設定反映を確認。
- 文書確認: READMEと設計資料の責務分割説明が実装構成と一致していることを確認。

**Decisions**

- 分割方針: 案A（View/Controller/StateMapper）を採用。
- 互換性: 外部互換は必要最小限変更を許容（起動経路の破壊は回避）。
- ドキュメント: READMEと設計資料を同一作業で更新。
