## Plan: PyInstaller spec安定化（Tk版）

one-folder 配布を前提に、現行 `spec` を「起動確実性」と「配布時の期待動作」に合わせて整えます。方針は、外部ツール（Ghostscript/pngquant）は同梱せず事前インストール必須、D&D（tkinterdnd2）は必須機能、依存定義は Tk 実装に合わせて整理です。  
このため、`spec` 単体の見直しだけでなく、`spec` と依存定義・実行時前提（README）の整合を同時に取る計画にします。特に高優先は、PDF系依存の import 失敗でアプリ全体が起動不能になるリスクの封じ込めと、D&D 必須要件を満たす PyInstaller 取り込み定義の明確化です。

**Steps**

1. 現行 packaging 前提を固定化する
   - one-folder 前提を [compressor_launcher_tkinter.spec](compressor_launcher_tkinter.spec) に明示（ビルドオプション、`console` 方針、`datas`/`hiddenimports` の意図を整理）
   - 起動経路の実体と差分がないか [compressor_launcher_tkinter.py](compressor_launcher_tkinter.py)、[frontend/bootstrap.py](frontend/bootstrap.py)、[frontend/ui_tkinter.py](frontend/ui_tkinter.py) を基準に確認

2. D&D 必須要件を満たす取り込み定義を設計
   - `tkinterdnd2` が配布先で必ず有効になるよう、`spec` の `hiddenimports`/必要データ取り込みを確定
   - optional import に依存したまま機能欠落しない受け入れ条件を [frontend/ui_tkinter.py](frontend/ui_tkinter.py#L47) 基準で定義

3. 起動不能リスク（PDF依存）を封じる変更方針を確定
   - [backend/core/pdf_utils.py](backend/core/pdf_utils.py#L8) と [backend/core/worker_ops.py](backend/core/worker_ops.py#L6) のトップレベル import 連鎖を見直し対象として特定
   - 「外部依存不足でもアプリ起動は維持、該当機能のみ無効化」の設計に合わせて実装修正点を洗い出し（実装担当へ引き渡し）

4. 外部ツール前提を配布仕様として統一
   - Ghostscript/pngquant は事前インストール必須の運用を [Documentation/README.md](Documentation/README.md#L155) と `spec` 運用手順に統一
   - 実行時検出ロジックの期待結果を [backend/capabilities.py](backend/capabilities.py#L17)、[backend/core/image_utils.py](backend/core/image_utils.py#L58)、[backend/core/pdf_utils.py](backend/core/pdf_utils.py#L189) に沿って整理

5. 依存定義を Tk 配布向けに一本化
   - [pyproject.toml](pyproject.toml) と [requirements.txt](requirements.txt) の差分を整理し、Tk版に不要な依存（例: `pyside6`）の扱いを統一
   - PyInstaller 実行環境の再現性を担保する最小依存セットを確定

6. build/run 手順の検証導線を固定
   - [compressor_launcher.ps1](compressor_launcher.ps1) と `spec` の組み合わせで、クリーンビルド→起動確認→主要機能確認（D&D含む）の手順を定義
   - ログ出力先・リソース配置の妥当性を [shared/configs.py](shared/configs.py#L20) と照合

**Verification**

- `pyinstaller compressor_launcher_tkinter.spec` で one-folder ビルド成功
- 生成物でアプリ起動、D&D 操作、主要圧縮フローが実行可能
- Ghostscript/pngquant 未導入時は「起動は成功し、該当機能のみ適切に案内/制限」
- 導入済み環境では PDF/画像最適化の外部連携処理が成功
- 依存インストール手順（`requirements`/`pyproject`）で再現ビルドできる

**Decisions**

- 配布形式: one-folder のみ
- 外部ツール: 事前インストール必須
- D&D: 必須機能として保証
- 依存定義: Tk版配布に合わせて整理
