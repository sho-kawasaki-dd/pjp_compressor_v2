## Prompt: Root整理と層分離の実装

あなたはこのリポジトリのリファクタリング担当です。以下の制約を守って、段階移行（1リリース互換あり）で構成整理を実装してください。

### 目的

- 最終状態として、プロジェクトルート直下の Python スクリプトは [compressor_launcher_tkinter.py](compressor_launcher_tkinter.py) のみとする。
- それ以外の Python スクリプトは `backend` と `frontend` に整理する。
- `configs` は [shared/configs.py](shared/configs.py) に集約する。
- `app` フォルダは最終的に削除する。

### 決定済み方針（固定）

- 移行方式: 段階移行（1リリースのみ互換維持）
- `app`: 最終的に削除
- `mp3_to_wav.py`: [backend/tools/mp3_to_wav.py](backend/tools/mp3_to_wav.py) へ移設
- `configs.py`: [shared/configs.py](shared/configs.py) に集約

### 実装フェーズ

1. **frontend 土台作成**
   - [frontend/](frontend) を新設し、[frontend/bootstrap.py](frontend/bootstrap.py) を追加。
   - [ui_tkinter.py](ui_tkinter.py) と [sound_utils.py](sound_utils.py) を `frontend` 側に移す準備を行う。

2. **shared/configs の導入**
   - [shared/configs.py](shared/configs.py) を作成し、既存 [configs.py](configs.py#L85-L101) の定数を移管。
   - `APP_BASE_DIR` は source 実行時に従来どおりプロジェクトルートを指すよう調整し、既定の `input_files` / `output_files` / `sounds` の解決結果を維持する。

3. **起動経路の切替**
   - [compressor_launcher_tkinter.py](compressor_launcher_tkinter.py#L23) の import を `app.bootstrap` から `frontend.bootstrap` へ変更。
   - [compressor_launcher_tkinter.spec](compressor_launcher_tkinter.spec#L10-L17) の hiddenimports も同様に更新。

4. **backend への再配置**
   - [compressor_utils.py](compressor_utils.py) を `backend` 配下（例: `backend/core`）へ移設。
   - backend services/orchestrator の参照先を新パスへ統一。

5. **ツールスクリプト移設**
   - [mp3_to_wav.py](mp3_to_wav.py) を [backend/tools/mp3_to_wav.py](backend/tools/mp3_to_wav.py) へ移動。
   - 単体実行入口は維持。

6. **互換期間（1リリース）**
   - 旧 import 経路を壊さない最小限の互換モジュールを残す。
   - この期間中に内部 import を `shared/frontend/backend` の正式経路へ置換完了する。

7. **最終クリーンアップ**
   - [app/](app) を削除。
   - 互換モジュールを撤去。
   - ルート直下の Python スクリプトが [compressor_launcher_tkinter.py](compressor_launcher_tkinter.py) のみであることを確認。

8. **ドキュメント同期**
   - [Documentation/README.md](Documentation/README.md#L84-L104) と [Documentation/flow_sequence_and_class_diagrams.md](Documentation/flow_sequence_and_class_diagrams.md) の起動チェーン／構成図を実装に合わせて更新。

### 非機能制約

- 既存機能の挙動を変えない（UI 操作、圧縮処理、cleanup、通知音）。
- 不要な仕様追加は行わない。
- 変更は最小限かつ段階的に行う。

### 完了条件（Acceptance Criteria）

- ルート直下に残る Python スクリプトは [compressor_launcher_tkinter.py](compressor_launcher_tkinter.py) のみ。
- `configs` の参照が [shared/configs.py](shared/configs.py) に集約されている。
- `app` フォルダが削除され、起動経路は launcher → frontend.bootstrap になっている。
- 以下が成功する:
  - `python compressor_launcher_tkinter.py`
  - `pyinstaller compressor_launcher_tkinter.spec`
  - `.\compressor_launcher.ps1`

### 実行時の注意

- まず import とパス解決の安全性を確保し、その後にファイル移動を行うこと。
- 互換層の撤去は、正式 import 経路への置換完了後に行うこと。
