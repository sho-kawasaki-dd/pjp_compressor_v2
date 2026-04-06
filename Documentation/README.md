# フォルダ一括圧縮アプリ（PDF・画像対応版）

PDF、JPG、PNGファイルを「フォルダ単位」で一括圧縮できるGUIアプリケーションです。
PDF圧縮は Ghostscript（任意）またはネイティブエンジン（PyMuPDF + pikepdf）を利用し、画像はPillowによる品質指定圧縮、PNGはpngquant（不可逆）も選択可能です。さらに画像の一括リサイズ（手動指定 / 長辺指定、アスペクト比保持）にも対応し、並列処理で大量ファイルにも対応します。ネイティブ PDF 非可逆圧縮では、PDF 内 PNG 系画像を PNG のまま減色圧縮でき、WeasyPrint 由来の soft mask 付き透過画像も透過を保ったまま再圧縮できます。加えて、PDF 埋め込み画像と単体画像ファイルの両方で CMYK 画像を ICC プロファイル優先で RGB へ正規化するため、黒潰れや保存時のモード不整合を起こしにくくしました。

本アプリはフロントエンド/バックエンド分離構成で、起動は `compressor_launcher_tkinter.py` → `frontend/bootstrap.py` → `frontend/ui_tkinter.py` の順で行います。圧縮処理は `backend` 配下の契約・オーケストレータ経由で実行されます。

## 関連ドキュメント

- 画面と処理の全体像（HTML）: [フロー図、シーケンス図およびクラス図](./flow_sequence_and_class_diagrams.html)
- 画面と処理の全体像（Markdown）: [flow_sequence_and_class_diagrams.md](./flow_sequence_and_class_diagrams.md)

## 主な機能

- PDF 圧縮（Ghostscript / ネイティブエンジンを選択可能）
  - Ghostscript: PDF再蒸留（プリセット選択可）
  - ネイティブ: PyMuPDF（画像再圧縮）+ pikepdf（可逆最適化）
  - 外部ツール依存（Ghostscript/pngquant）欠落時は機能単位で劣化起動（アプリは起動継続）
  - エンジン可用性の再検出はアプリ再起動にて行う仕様
  - Ghostscript設定: プリセット選択（/screen /ebook /printer /prepress /default）またはカスタムDPI指定
  - Ghostscript設定: pikepdf構造最適化（可逆）を併用可能
  - ネイティブ設定: モード選択（非可逆 / 可逆 / 両方）、DPI、JPEG品質、PNG品質、可逆オプション
  - ネイティブ PDF の PNG 系画像は PNG のまま量子化し、pngquant がある環境では PNG 品質スライダーを使って quality 範囲を自動設定
  - ネイティブ PDF の soft mask 付き画像は alpha を再構成してから再圧縮し、透過がある画像は PNG 経路を優先して黒背景化を避ける
  - ネイティブ PDF の埋め込み CMYK ラスター画像は、再圧縮前に ICC プロファイル優先で RGB へ変換し、JPEG/PNG のどちらへ送っても後段の色処理を安定させる
  - pngquant が無い環境では、PDF 内 PNG 系画像は Pillow の 256 色固定減色へ自動フォールバックし、PDF 用 PNG 品質スライダーは無効化
  - ネイティブ設定の調査補助: 出力設定の「デバッグモードで出力」をONにすると、PyMuPDF 非可逆圧縮時だけ埋め込み画像ごとの診断 stats を標準出力へ出力
  - debug stats では `soft_mask_seen`、`soft_mask_applied`、`soft_mask_failed`、`cmyk_converted` も確認可能
- 画像圧縮
  - JPG/PNGをPillowで圧縮（品質0-100）
  - PNGをpngquantで不可逆圧縮（quality範囲自動設定）
  - CMYK 入力画像は保存や pngquant 前処理の前に RGB へ正規化し、単体画像圧縮でも色空間差による失敗を避ける
  - 画像リサイズ（任意）：
    - モード選択（手動: 幅/高さ指定、または 長辺指定）
    - 長辺指定はプリセットドロップダウン（640/800/1024/1280/1600/1920/2048/2560/3840）から選択可能（任意入力も可）
    - アスペクト比保持の選択
    - パフォーマンス最適化：幅/高さの入力は処理開始時に一度だけ数値化し、空欄・非数値は0に自動補正（入力時の逐次検証は行わずUIを軽量化）
- 高速・安定
  - ZIP展開オプションON時、ZIPアーカイブは入力フォルダを変更せず一時作業領域で再帰展開（最大25サイクルで打ち切り、循環ループを防止）
  - ZIP展開時は path traversal・絶対パス・Windowsドライブ指定・symlink相当 entry を拒否し、危険な member は展開しない
  - ZIP展開時は 1 ZIP あたり `member数 <= 10000`、`展開後合計サイズ <= 1,000,000,000 bytes` を上限として扱う
  - ZIP展開オプションON時、展開由来ファイルは `出力フォルダ/ZIPの元相対パス/ZIPのstem/` 配下へ内部構造を維持して出力
  - ThreadPoolExecutorによる並列処理
  - 出力設定の新オプション（既定OFF）:
    - 「圧縮対象外のファイルを出力フォルダへコピー」をONにすると、未対応拡張子（`.pdf/.jpg/.jpeg/.png` 以外）を入力フォルダの相対構造を保ったまま出力へコピー
    - ON時は、圧縮対象拡張子でも圧縮失敗したファイルをフォールバックとして元ファイルコピー
  - ZIP処理の組み合わせ仕様（`ZIP展開してから圧縮` × `ミラー圧縮`）:
    - ミラーOFF + ZIP展開ON: ZIP由来の圧縮対象のみ出力（非対象は出力しない）、入力ZIPは保持
    - ミラーOFF + ZIP展開OFF: ZIP処理はスキップ（従来ログは維持）
    - ミラーON + ZIP展開ON: 入力ZIPを出力へコピーし、ZIP由来の圧縮対象を圧縮、非対象もコピー
    - ミラーON + ZIP展開OFF: 入力ZIPを出力へコピー（ZIPに対する処理）
  - Before/Afterのファイルサイズをログに表示
  - 処理後に合計削減量と削減率を統計表示（PDF/JPG/PNGなど実際に圧縮を実施したファイルのみを集計）
  - CSVログ出力（任意）：各ファイルの処理結果を `compression_log_YYYYMMDD_HHMMSS.csv` に保存（入力/出力パス、拡張子、処理方法、サイズ、削減量/率）
  - デバッグモード出力（任意）：出力設定のトグルをONにした場合、ネイティブ PDF の非可逆段のみ標準出力へ詳細診断を出力。GUI のログタブと CSV 出力には混在させない
  - 大量ファイルでもUIが固まらないように処理は別スレッドで実行
- 使いやすいUI
  - 入力フォルダのドラッグ＆ドロップ
  - ノートブックに `アプリ設定` タブを追加
  - 起動時効果音の ON/OFF を切り替え可能
    - 対象は起動直後の `open_window.wav` と、デスクトップ既定フォルダ作成確認前の `notice.wav`
  - クリーンアップ確認時の効果音 ON/OFF を切り替え可能
    - 対象は入力/出力フォルダのクリーンアップ確認前の `warning.wav`
  - 効果音トグル状態を JSON に永続化し、再起動後も復元
  - 入出力フォルダのクリーンアップ（入力: .pdf/.jpg/.jpeg/.png/.zip、出力: .pdf/.jpg/.jpeg/.png/.csv。サブフォルダ含む）
  - 進捗バーと詳細ログ
  - 入力/出力フォルダの重なりを検知して自動リセット（警告とログを出力）
  - PDFエンジンの状態表示（Ghostscript / PyMuPDF / pikepdf）をラベルで表示（再検出はアプリケーション再起動によって行う）
  - Ghostscript未検出時のUI自動制御
    - Ghostscriptが無い場合、Ghostscriptエンジン選択は自動的に無効化されます
  - ネイティブ PDF 用 PNG 品質スライダーの動的無効化
    - システムに `pngquant` が無い場合、PDF 用 PNG 品質スライダーは無効化され「Pillow の 256 色固定減色へフォールバックするため無効」と注記されます
  - リサイズ UI の動的無効化（視覚的にグレー化）
    - アプリ起動時は「画像を一括リサイズする」がOFFのため、幅/高さの入力、アスペクト比保持、手動/長辺指定ラジオ、長辺指定ドロップダウンはグレーアウト
    - 画像リサイズがOFFの場合、手動/長辺指定ラジオと長辺指定ドロップダウンを無効化
    - 長辺指定モードでは、幅/高さ/アスペクト比保持の手動入力を無効化
    - 手動モードでは、長辺指定ドロップダウンを無効化
  - pngquantトグルの自動無効化
    - システムに `pngquant` が無い場合、トグルは無効化され「未検出のため無効」と表示
  - 入力値の安全側正規化
    - Ghostscript の custom DPI は UI と backend の両方で許容レンジへ丸める
    - JPG/PNG 品質値は backend 側で 0-100 に正規化し、極端値でも処理全体が落ちないようにする

## 動作環境と依存

- Python 3.13+
- 必須: Pillow
- 必須: PyMuPDF・pikepdf（ネイティブPDF処理）
- 必須: tkinterdnd2（ドラッグ＆ドロップ）
- 任意: Ghostscript（PDF再蒸留）, pngquant（PNG不可逆圧縮）, pygame（サウンド再生）

依存検出の実装仕様:

- `backend/capabilities.py` が起動時に可用性を検出します。
  - Pythonモジュール: `fitz` / `pikepdf`
  - 実行ファイル: `ghostscript` (`gswin64c` / `gswin32c` / `gs`) / `pngquant`
- 検出結果は `CapabilityReport`（`backend/contracts.py`）としてUIへ反映されます。
- 外部ツール未導入でもアプリは起動継続し、該当機能のみ無効化されます。
- `pngquant` が未導入でも PDF ネイティブ非可逆圧縮は継続し、PDF 内 PNG 系画像だけが Pillow の 256 色固定減色へフォールバックします。
- Ghostscript / pngquant の呼び出しは `subprocess.run([...])` の引数配列で実行し、shell を経由しません。
- Ghostscript / pngquant の呼び出しには timeout を設定し、引数は安全側に正規化します。

仮想環境の作成を推奨します（PowerShell の例）:

カレントディレクトリを `pjp_compressor_v2` フォルダに設定してから次のコマンドを入力してください。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install Pillow pymupdf pikepdf tkinterdnd2 pygame
```

requirements.txt を利用する場合:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

## 実行ファイル化（PyInstaller / one-folder）

本プロジェクトは `compressor_launcher_tkinter.spec` を使った one-folder 配布を前提としています。

事前に `pyinstaller` をインストールしてください（`requirements.txt` を使う場合は同時に導入されます）。

```powershell
python -m pip install pyinstaller
```

```powershell
python -m PyInstaller --clean .\compressor_launcher_tkinter.spec
```

生成先は `dist/PDF_JPG_PNG_Compressor_v2.5.2/` です。配布時はこのフォルダ全体を渡してください。

補足:

- one-folder 配布では `sounds/`、`images/` に加えて `frontend/config_data/ui_catalogs.json` も同梱されます。
- UI の表示用カタログと `app_settings` は JSON から読み込むため、spec を介さず独自ビルドする場合も `frontend/config_data/` を配布物へ含めてください。

PowerShell スクリプト経由で実行する場合:

- アプリ起動: `./compressor_launcher.ps1 -Mode Run`
- ビルド実行: `./compressor_launcher.ps1 -Mode Build`

システムツールのインストール:

PCのOSがWindowsの場合は、CLIパッケージ管理ツールChocolateyを使うのがおすすめです。

- pngquant: Windows: `choco install pngquant` / macOS: `brew install pngquant` / Ubuntu/Debian: `sudo apt install pngquant`
- Ghostscript: Windows: `choco install ghostscript` / macOS: `brew install ghostscript` / Ubuntu/Debian: `sudo apt install ghostscript`

## 使い方（手順）

1. アプリを起動します（仮想環境に入って `python compressor_launcher_tkinter.py`）。
2. 入力フォルダを指定します（参照ボタンまたはドラッグ＆ドロップ）。
3. 出力フォルダを指定します（Windowsは初回起動時にデスクトップ作成提案あり）。
4. 必要なら `アプリ設定` タブで、起動時効果音とクリーンアップ確認時効果音の ON/OFF を切り替えます。
5. 圧縮設定を行います（PDFエンジン選択、必要に応じてネイティブ/GS各設定、画像品質、リサイズ）。
6. 圧縮を開始します（ZIP自動展開、進捗表示、CSVログ出力）。必要に応じて「圧縮対象外のファイルを出力フォルダへコピー」をONにします（既定はOFF）。
   - WeasyPrint 由来 PDF などで PyMuPDF の画像再圧縮が効いているか確認したい場合は、「デバッグモードで出力」をONにすると標準出力へ画像 xref ごとの統計が出ます。
7. 統計を確認します（合計サイズ、削減量、削減率）。
8. 必要に応じてクリーンアップを実行します（入力/出力フォルダの対象拡張子を削除）。

## モジュール構成

### 起動とフロントエンド

- `compressor_launcher_tkinter.py`: 起動エントリポイント（例外処理・クラッシュログ）
- `frontend/bootstrap.py`: 起動順序の集約（UI生成・起動時サウンド、起動音トグル適用）
- `frontend/ui_tkinter.py`: Tkinter GUIのファサード（起動時副作用・App初期化・モジュール接続・既定フォルダ確認音の制御）
- `frontend/ui_tkinter_state.py`: Tkinter `Variable` 群の状態初期化責務
- `frontend/ui_tkinter_view.py`: ウィジェット構築・レイアウト責務
- `frontend/ui_tkinter_controller.py`: イベント処理・入力検証・非同期実行・進捗反映責務、クリーンアップ音とアプリ設定保存の制御
- `frontend/ui_tkinter_mapper.py`: UI状態から `CompressionRequest` への変換責務
- `frontend/ui_contracts.py`: フロントエンド内の型契約（Protocol）責務

### 契約とオーケストレーション

- `backend/contracts.py`: FE/BE境界契約（Request / Event / Capability / Result）
- `backend/capabilities.py`: 依存可用性検出（fitz / pikepdf / ghostscript / pngquant）
- `backend/orchestrator/job_runner.py`: 圧縮ジョブの実行オーケストレーション

契約駆動の主要データ:

- `CompressionRequest`: UI設定をバックエンドへ渡すDTO
- `CompressionRequest.debug_mode`: デバッグトグルの状態。現時点では PyMuPDF 非可逆圧縮の標準出力診断にのみ使用
- `ProgressEvent` (`kind`: `log` / `progress` / `stats` / `status` / `error`): UI更新イベント
- `CapabilityReport`: 起動時の依存可用性レポート

### 設定レイヤ

- `shared/runtime_paths.py`: 通常実行と PyInstaller 実行で共通に使う実行時パス解決責務
- `backend/settings.py`: backend が所有する処理既定値（PDF 圧縮既定値、Ghostscript 既定プリセット、許可モード）
- `frontend/settings.py`: frontend が所有する UI 既定値、cleanup 対象、リソースパス、UI カタログ / app_settings の JSON 読込保存責務
- `frontend/config_data/ui_catalogs.json`: UI 表示用カタログと `app_settings` を保持する JSON（PDF モード表示名、Ghostscript プリセット表示名、長辺プリセット、効果音トグル既定値）
- `shared/configs.py`: 旧 import パス互換のための再エクスポート層。新規コードでは直接依存しない前提

### サービス層とコア処理

- `backend/services/*.py`: PDF・画像・ZIP・クリーンアップ責務の分割入口
- `backend/core/pdf_utils.py`: PDF圧縮（PyMuPDF / pikepdf / Ghostscript）責務
- `backend/core/image_utils.py`: 画像圧縮（Pillow / pngquant）責務
- `backend/core/archive_utils.py`: ZIP再帰展開責務
- `backend/core/file_ops.py`: クリーンアップ／対象件数カウント責務
- `backend/core/worker_ops.py`: 単一ファイル単位の処理ディスパッチ責務
- `backend/core/format_utils.py`: 表示用フォーマット（human_readable）責務
- `backend/core/compressor_utils.py`: 互換shim（公開API再エクスポート + compress_folder委譲）
- `frontend/sound_utils.py`: pygameを使った効果音再生（UI依存を持たない純粋ユーティリティ）

### 実行パイプライン（要約）

1. UI設定を `frontend/ui_tkinter_mapper.py` が `CompressionRequest` に変換
2. `backend/orchestrator/job_runner.py` がジョブを実行
3. ZIP展開ON時はZIPを一時作業領域で展開（入力不変）し、通常入力ファイルとZIP由来ファイルをタスク化
4. `ThreadPoolExecutor(max(4, cpu_count()))` で並列実行
5. `backend/core/worker_ops.py` が拡張子別にサービス/コアへディスパッチ
6. `ProgressEvent` でログ・進捗・統計をUIへ反映
7. CSV有効時は `compression_log_YYYYMMDD_HHMMSS.csv` を出力

## よくある質問

- Q: Ghostscriptとネイティブエンジン（PyMuPDF + pikepdf）のどちらが良いですか？
  - A: Ghostscriptは再蒸留ベースで高い圧縮効果が期待できます。ネイティブエンジンはPython環境のみで動作しやすく、可逆最適化も併用できます。目的（画質優先/導入容易性）で選択してください。
- Q: PDF圧縮の設定はどのように使い分ければよいですか？
  - A: ネイティブを選ぶと、モード（非可逆/可逆/両方）・DPI・JPEG品質・PNG品質・可逆オプションを設定できます。JPEG 品質は PDF 内の JPEG 系画像に、PNG 品質は PDF 内の PNG 系画像の pngquant 量子化に使われます。Ghostscriptを選ぶと、プリセットまたはカスタムDPIを使った再蒸留に加え、必要ならpikepdf構造最適化を併用できます。
- Q: ネイティブ PDF の PNG 品質スライダーはいつ効きますか？
  - A: `pngquant` が検出されている環境で、ネイティブ PDF 圧縮のモードが「非可逆」または「両方」のときに有効です。このとき quality 範囲は通常 PNG 圧縮と同じく `max=スライダー値`、`min=max-20` で自動計算されます。
- Q: `pngquant` が無い環境では PDF 内 PNG はどう圧縮されますか？
  - A: ネイティブ PDF 非可逆圧縮は継続し、PDF 内 PNG 系画像だけが Pillow の 256 色固定減色 PNG へフォールバックします。この場合、PDF 用 PNG 品質スライダーは UI 上で無効化され、値は backend では使われません。
- Q: WeasyPrint 由来 PDF の透過 PNG はどのように扱われますか？
  - A: WeasyPrint などが生成する PDF では、透過が画像本体ではなく `SMask` として分離されていることがあります。現在のネイティブ非可逆圧縮では、この soft mask を再構成してから再圧縮し、透過がある画像は PNG 経路へ送るため、黒背景化を起こしにくくしています。
- Q: soft mask の復元が失敗したかどうかは確認できますか？
  - A: できます。出力設定の「デバッグモードで出力」をONにすると、PyMuPDF 非可逆段の標準出力に `soft_mask_seen`、`soft_mask_applied`、`soft_mask_failed`、`cmyk_converted` が出るため、対象 PDF に soft mask が含まれていたか、復元に失敗したか、CMYK 画像を RGB へ変換したかを追えます。
- Q: CMYK の JPEG や PDF 埋め込み画像はどのように扱われますか？
  - A: 現在の実装では、PDF 埋め込みラスター画像と単体画像ファイルの両方で、読み込み直後に CMYK を RGB へ正規化します。ICC プロファイルを持つ画像は `ImageCms.profileToProfile()` で sRGB へ寄せ、ICC が無いか壊れている場合も `convert('RGB')` で安全側にフォールバックするため、黒潰れや保存時のモード不整合を起こしにくくしています。
- Q: PNG を大幅に圧縮したいです。どのように設定すればよいですか？
  - A: pngquantでの圧縮をONにしてください。品質範囲（min-max）はスライダーの値をもとに設定されます（max=スライダー値、min=max-20）。
- Q: 画像のリサイズ設定はどのように動きますか？
  - A: 手動モードでは幅/高さを指定可能、アスペクト比を保持するかどうかを選べます。アスペクト比を保持する場合は、片方の数値の入力で十分です。（もう一方は0でOK。）両方入力した場合は、小さいほうのピクセル数に合わせます。長辺モードでは長辺がドロップダウンの指定ピクセルになるように等比縮小します。
    - 幅/高さが空欄や非数値の場合は自動で0に補正されます（処理開始時に一度だけ判定）。また、設定値の小数点以下は処理開始時に切り捨てられます。
    - 手動モードで幅/高さの両方を0にした場合はリサイズされません。長辺モードで長辺を0にした場合もリサイズされません。
- Q: CSVログには何が記録されますか？
  - A: 各ファイルの入力/出力パス、拡張子、処理方法（Ghostscript/Native PDF/Pillow/pngquant/無処理）、元サイズ、出力サイズ、削減量、削減率が記録されます。
- Q: CSVログの無効化や保存先の変更はできますか？
  - A: できます。設定画面の「CSVログを出力する」のチェックを外すと無効化。保存先を変更する場合はその右の入力欄にパスを直接入力するか「参照」ボタンから選択してください。未指定の場合は出力フォルダにタイムスタンプ付きファイルが作成されます。
- Q: 効果音は無効化できますか？
  - A: できます。`アプリ設定` タブで「起動時に効果音を鳴らす」「クリーンアップ確認時に効果音を鳴らす」を個別に切り替えてください。起動時トグルは `open_window.wav` と `notice.wav` を、クリーンアップ時トグルは `warning.wav` を対象にします。設定は `frontend/config_data/ui_catalogs.json` の `app_settings` に保存され、次回起動時にも復元されます。
- Q: 「デバッグモードで出力」をONにすると何が起きますか？
  - A: 現時点では、ネイティブ PDF 圧縮のうち PyMuPDF による非可逆画像再圧縮段だけが詳細診断を標準出力へ出します。GUI のログタブ、進捗表示、CSV ログの形式は変わりません。
- Q: クリーンアップで何が削除されますか？
  - A: 入力フォルダは .pdf/.jpg/.jpeg/.png/.zip、出力フォルダは .pdf/.jpg/.jpeg/.png/.csv が対象です。サブフォルダ内の該当ファイルも削除されます。取り消し不可のため慎重に実行してください。
- Q: 「圧縮対象外のファイルを出力フォルダへコピー」をONにすると何が起きますか？
  - A: 未対応拡張子（`.pdf/.jpg/.jpeg/.png` 以外）を入力と同じ相対フォルダ構造で出力先へコピーします。加えて、圧縮対象拡張子でも圧縮に失敗したファイルはフォールバックとして元ファイルを出力先へコピーします。
- Q: ZIP展開オプションをONにしたとき、入力フォルダ内のZIPはどうなりますか？
  - A: 入力フォルダのZIPはそのまま残ります。展開は一時作業領域で行われるため、入力フォルダ内に展開ファイルは残りません。
- Q: ZIP展開時の出力先はどのようになりますか？
  - A: 各ZIPごとに `ZIPのstem` 名フォルダを作成し、`出力フォルダ/ZIPの元相対パス/ZIPのstem/` 配下へZIP内部構造を維持して出力します。
- Q: ZIP はどのくらいのサイズまで現実的に処理できますか？
  - A: コード上は「1 ZIP あたり展開後合計 1 GB 未満、member 数 10000 以下」が上限です。ただし実運用では、ZIP を一時領域へ複製してから展開し、その後に出力ファイルも作るため、安定運用の目安は ZIP 実サイズ 300 MB から 500 MB 程度です。画像や PDF が中心のため圧縮率が低いことが多く、ZIP 実サイズと展開後サイズは近くなりやすい前提で考えてください。
- Q: ZIP 展開時にどのくらい空き容量を見ておけばよいですか？
  - A: 最低でも「展開後サイズの 2.5 倍から 3 倍」程度の空き容量を推奨します。一時領域への ZIP 複製、展開済みファイル、圧縮後の出力ファイルが同時に存在する時間帯があるためです。特に同一ドライブで入力・一時・出力を扱う場合は余裕を大きめに見てください。

## 自動テスト

pytest による自動テストは `tests/` 配下に集約しています。通常開発と CI では `unit + integration` を標準実行とし、GUI を含む重めの確認は `regression` として分離しています。

- `tests/conftest.py`
  - 共有 fixture 群です。サンプル画像、ZIP、CapabilityReport、Tk 回帰用 App 初期化を提供します。
- `tests/unit/`
  - `backend/contracts.py`、`backend/capabilities.py`、`backend/core/archive_utils.py`、`backend/core/image_utils.py`、`frontend/ui_tkinter_mapper.py`、`frontend/settings.py` / `shared/configs.py` 互換レイヤ、`backend/core/pdf_utils.py` の xref 処理、soft mask 再構成、PNG/JPEG 分岐、Ghostscript/pngquant の入力正規化・timeout・ZIP 安全化などの純粋ロジックを検証します。
- `tests/integration/`
  - `backend/orchestrator/job_runner.py` と `frontend/ui_tkinter_controller.py` を中心に、CSV 出力、ZIP 展開、フォールバックコピー、イベント通知、スレッド起動、UI から渡る極端値の clamp 伝播を検証します。
- `tests/regression/`
  - 旧 `scripts/tkinter_regression_check.py` を pytest 化した GUI 回帰です。フォルダ選択、D&D、CSV パス選択、圧縮開始、クリーンアップ、入力/出力重なり防止、ZIP 組み合わせをまとめて確認します。

推奨実行コマンド:

```powershell
python -m pytest -m "unit or integration"
```

通常の開発確認と CI は上記を使用してください。

```powershell
python -m pytest -m regression
```

GUI を含む回帰確認は必要時のみ実行してください。

```powershell
python -m pytest
```

すべてのテストをまとめて実行する場合は上記です。

注意:

- Tk を使う回帰テストは `requires_tk` マーカー付きです。
- 実行中の Python に Tcl/Tk ランタイムが正しく入っていない環境では、自動的に skip されます。
- Ghostscript や pngquant を使う将来の外部依存テストは `requires_external` で分離できる構成です。
- 旧 `scripts/tkinter_regression_check.py` は `tests/regression/test_tkinter_regression.py` へ移植済みです。

## 手動回帰チェック（5分版）

- [ ] `python compressor_launcher_tkinter.py` で起動し、画面が表示される。
- [ ] PDFエンジン状態ラベル（PyMuPDF / pikepdf / GS）が表示される。
- [ ] 「入力フォルダ」「出力フォルダ」を選択し、値が反映される。
- [ ] 入力欄へファイルまたはフォルダをD&Dしたとき、入力フォルダが更新される。
- [ ] JPG/PNGを含む入力で「圧縮開始」を実行し、ログタブ切替（設定ON時）・進捗バー更新・統計更新が行われる。
- [ ] 出力先に圧縮ファイルが生成される。
- [ ] CSV出力ON時にログファイルが生成される。
- [ ] 出力設定の「デバッグモードで出力」が既定OFFで表示される。
- [ ] 同オプションON時、ネイティブ PDF の非可逆圧縮でのみ標準出力へ debug summary/details が出る。
- [ ] 出力設定の「圧縮対象外のファイルを出力フォルダへコピー」が既定OFFである。
- [ ] 同オプションON時、未対応拡張子が相対構造を維持して出力先へコピーされる。
- [ ] 同オプションON時、圧縮失敗ファイルがフォールバックコピーされる。
- [ ] リサイズON（手動または長辺指定）で出力画像サイズが設定に従う。
- [ ] 出力フォルダの「クリーンアップ」で対象拡張子ファイルが削除される。
- [ ] 処理中に終了した場合、確認ダイアログが出る。

補助: 自動回帰相当の確認は `python -m pytest -m regression` で実行できます。

## 注意事項

- 大量のファイルを扱う場合、並列処理で高速化しますが、ディスク I/O によるボトルネックは発生し得ます。
- PDF圧縮は Ghostscript とネイティブ（PyMuPDF + pikepdf）を選択可能です。エンジン可用性の再検出はアプリ再起動にて行う仕様です。
- Ghostscript使用時はプリセットまたはカスタムDPIを指定でき、必要に応じてpikepdfの可逆最適化も併用できます。
- Ghostscriptが未検出の環境では、Ghostscriptエンジン選択は自動的に無効化されます。
- pngquantが未検出の環境では、pngquantトグルは自動的に無効化されます。
- pngquantやGhostscript は**外部ソフトウェアとしてシステムにインストールする必要があります**（pythonのpipモジュールではインストールできません）。
- 入力フォルダと出力フォルダが重なる場合は、ファイル破損を避けるため自動的に両方ともデフォルトフォルダにリセットされ、警告とログが出ます。

## 開発者向けメモ

- 入力検証の最適化: リサイズの幅/高さは処理開始時に一度だけ文字列から数値化し、空欄・非数値は0に補正。入力時の逐次検証を省きUIイベント負荷を低減。
- 並列処理: `compress_folder()` は `ThreadPoolExecutor` を用いてファイル単位で並列化（`max(4, cpu_count())`）。大量ファイルでスループット改善。
- I/O ボトルネックについて: 画像/PNG/PDFの読み書き速度はストレージのディスク I/O 能力に依存します。CPUスレッドの並列度を上げてもディスク性能がボトルネックになる場合があります。
- UI分離: `ui_tkinter.py` はファサードとして責務を束ね、状態/ビュー/コントローラ/DTOマッパーを分離。圧縮はバックグラウンドスレッドで実行し、Tkのメインスレッドはログと進捗更新のみを担当（UIのフリーズ防止）。
- 実行時外部ツール検出と例外処理: Ghostscript/pngquantは実行時に `shutil.which` で検出し、未導入でも致命化せず機能単位で劣化します。
- 外部ツール呼び出しの安全化: Ghostscript / pngquant は shell を経由せず引数配列で起動し、timeout・引数正規化・ファイル引数区切りを入れて、極端値や不正なファイル名で壊れにくい構成にしています。
- ZIP 展開の安全化: path traversal・絶対パス・Windows ドライブ指定・symlink 相当 entry を拒否し、1 ZIP あたりの member 数と展開後合計サイズにも上限を設けています。
- ZIP 運用上限の目安: コード上限は展開後 1 GB ですが、入力・一時・出力を同時に持つため、日常運用では ZIP 実サイズ 300 MB から 500 MB 程度を標準上限として扱うのが無難です。
- バックエンド境界: UIは `CompressionRequest` を発行し、`ProgressEvent` 購読でログ/進捗/統計を反映します。
- CSVログ: 1回のオープンで逐次追記し、行ごとにフラッシュを強制しない設計（過度な同期 I/O を回避）。
- 画像リサイズの計算: 長辺指定時の比率計算は軽量で、Pillowのリサイズ/保存が主なコスト。不要な再計算を避けるため設定を一度だけ作成。
- 設定の責務分離: runtime パス解決は `shared/runtime_paths.py`、backend 既定値は `backend/settings.py`、frontend の UI 設定と表示カタログは `frontend/settings.py` + `frontend/config_data/ui_catalogs.json` に分離。
- JSON 化の方針: Path、OS 分岐、PyInstaller 判定は Python に残し、純粋データだけを JSON へ外出しする。
- PyMuPDF 非可逆圧縮の xref 走査: `page.get_images(full=True)` は「resources に見えている画像」まで返すため、WeasyPrint 系 PDF では先頭ページの `no_rect` 判定を xref 単位で失敗キャッシュすると、後続ページで実描画される画像まで再圧縮対象から外れてしまう。
- そのため `compress_pdf_lossy()` は `page.get_image_info(xrefs=True)` ベースへ切り替え、実描画画像だけを対象にしつつ、同じ xref は 1 回だけ処理する構造へ変更した。

### 2026年3月11日追記

- frontend 配下の Pylance 警告を、実行時挙動を変えずに解消。
- `frontend/ui_contracts.py` を追加し、`frontend/ui_tkinter_mapper.py` の `app: Any` を Protocol ベースの型契約へ置換。
- `frontend/ui_tkinter_state.py` で Tkinter `StringVar` / `IntVar` / `BooleanVar` を明示的に型注釈化。
- `frontend/ui_tkinter_view.py` で、widget 属性・controller/state 依存・Tk 本体前提をクラス属性注釈と局所 `cast` で明示化。
- `tkinterdnd2` の `drop_target_register` / `dnd_bind` は局所 Protocol で扱い、広域 suppress を避ける構成へ調整。
- frontend 全体の Pylance 診断で警告 0 を確認。
- `tests/regression/test_tkinter_regression.py` へ GUI 回帰を移植し、pytest から選択実行できるよう整理。
- `frontend/ui_tkinter_controller.py` の保守性改善を目的に、controller mixin が依存する Tk 変数・Widget・ランタイム属性・Tk メソッドを `frontend/ui_contracts.py` の Protocol として明文化。
- controller 側は Protocol ベースの `cast` に統一し、`after()` を使ったメインスレッド更新を helper 経由へ整理。Pylance 上の unknown attribute 警告を、実行時挙動を変えずに解消。
- D&D イベントの `event.data` は局所 Protocol で扱い、TkinterDnD 依存の動的オブジェクトを controller 内へ閉じ込める構成へ調整。
- `frontend/sound_utils.py` を型整理し、module docstring の位置修正、公開関数の引数・戻り値型付与、`Path | str` の明示、pygame 任意依存の型狭義化を実施。
- `frontend/ui_tkinter_controller.py`、`frontend/ui_contracts.py`、`frontend/sound_utils.py` の Pylance 診断でエラー 0 を確認。
- 起動確認として、messagebox と効果音を抑止した状態で `frontend.ui_tkinter.App` の生成と初期描画更新を実行し、初期化が正常終了することを確認。
  備考:

- GUIと圧縮ロジックは分離され、`backend` 層は UI非依存で再利用可能です。
- 設定は runtime / backend / frontend の責務ごとに分離され、`shared/configs.py` は互換レイヤとして残しています。
- 効果音の操作関数は `frontend/sound_utils.py` に切り出し、pygameが無い環境でも動作継続可能（初期化失敗時は警告のみ）。
- アプリ起動時はリサイズ関連UIを無効化してグレーアウト。

### 2026年3月15日追記 設定レイヤ再編

- `shared/configs.py` に混在していた runtime / backend / frontend 設定を責務単位で分離。
- 実行時パス解決を `shared/runtime_paths.py` へ移し、通常実行と PyInstaller 実行の基準パスをここへ集約。
- backend が使う PDF 圧縮既定値と Ghostscript 既定値を `backend/settings.py` へ移動。
- frontend が使う UI 既定値、cleanup 対象、リソースパス、表示カタログローダを `frontend/settings.py` へ移動。
- 純粋データのみを `frontend/config_data/ui_catalogs.json` へ外出しし、PDF モード表示名、Ghostscript プリセット表示名、長辺プリセットを JSON 管理へ変更。
- backend の `pdf_utils.py` は UI 表示用 `PDF_COMPRESS_MODES` 依存をやめ、`PDF_ALLOWED_MODES` による許可値検証へ変更。
- `shared/configs.py` は後方互換のための再エクスポート層へ縮小し、新規コードの依存先から外した。
- `compressor_launcher_tkinter.spec` に `frontend/config_data/` を追加し、one-folder 配布でも JSON カタログが欠けないようにした。
- `tests/unit/test_settings_split.py` を追加し、JSON ロード結果と `shared/configs.py` の互換再エクスポートを検証。

この改修が必要だった理由:

- `shared/configs.py` に runtime 判定、backend の処理既定値、frontend の表示用データが混在しており、責務境界が曖昧だったため。
- backend が UI 表示ラベルへ依存すると、処理条件の検証と画面表示の都合が結びつき、保守性が落ちるため。
- PyInstaller 配布時に必要なデータと Python ロジックを分けておかないと、配布物に何を含めるべきかが不明瞭になるため。
- JSON 化できる純粋データだけを外出しし、Path 計算や OS 分岐のような runtime ロジックは Python 側へ残すことで、構成の見通しと検証容易性を両立するため。

### 2026年3月15日追記 PyMuPDF 画像再圧縮の実描画 xref 走査化

- `backend/core/pdf_utils.py` の `compress_pdf_lossy()` を、`page.get_images(full=True)` ベースから `page.get_image_info(xrefs=True)` ベースへ変更。
- 実際にページ上へ描画されている画像だけを対象にし、`bbox` から実表示サイズを取得して DPI を計算するように変更。
- 同じ xref は `processed_xrefs` で 1 回だけ処理し、`replace_image()` 後に別ページで再 replace しない構造へ整理。
- `skip_no_rect` 系ノイズを避けるため、ページ resources 上は見えていても当該ページでは未描画という xref を踏まないようにした。
- `tests/unit/test_pdf_utils.py` を追加し、`get_image_info(xrefs=True)` を使うこと、同じ xref を 1 回だけ処理すること、xref 欠落や zero bbox を安全にスキップすることを unit テストで固定。

この改修が必要だった理由:

- `page.get_images(full=True)` は「そのページの resources に登録された画像」を返すため、「そのページで実際に描画されている画像」とは一致しないことがあるため。
- 特に WeasyPrint 系 PDF では、先頭ページの resources に後続ページの画像 xref が見えていても、そのページでは `get_image_rects(xref)` が空になるケースがあり、旧実装ではこれを xref 単位の失敗として扱っていたため。
- その結果、1 ページ目で負の結果をキャッシュすると後続ページで実描画される画像も即 skip され、`replaced_count=0` のまま圧縮効果を取り逃がしていたため。
- 実描画画像ベースの走査へ寄せることで、原因分析に使う debug summary も `skip_already_processed`、`replaced`、`skip_not_smaller` のように意味が揃い、挙動を追いやすくするため。

### 2026年3月16日追記

- ネイティブ PDF 非可逆圧縮で、PDF 内 PNG 系画像を JPEG へ変換せず、PNG のまま量子化するように変更
- PDF ネイティブ設定の `PNG→JPEG変換` を廃止し、`PNG品質` スライダーを追加
- `pngquant` が利用可能な環境では、PDF 用 PNG 品質スライダー値を上限に `min=max-20` の quality 範囲で量子化
- `pngquant` が未導入の環境では、Pillow の 256 色固定減色 PNG へ自動フォールバックし、PDF 用 PNG 品質スライダーは UI 上で無効化
- request/worker 配線は `pdf_png_quality` ベースへ移行し、デバッグ出力やログでも PNG 量子化経路が追えるように整理

今回の版では、PDF 内の PNG 系画像を JPEG 化して逃がす旧挙動を完全にやめ、PNG のまま圧縮経路を選べるように整理しました。これにより、透明情報や PNG 系素材の扱いを崩しにくくしつつ、`pngquant` がある環境では圧縮率を稼ぎ、無い環境でもアプリ全体は止めずに減色処理を継続できます。

### 2026年3月30日追記

- ネイティブ PDF 非可逆圧縮で、PDF 画像の `SMask` を読み取って透過を再構成する処理を追加
- WeasyPrint などが生成する soft mask 付き画像は、内部拡張子が JPEG 系でも透過付き PNG 経路へ送るように変更
- soft mask の抽出または復元に失敗した場合は処理全体を止めず、従来経路へフォールバックしつつ debug stats で追跡可能に整理
- `tests/unit/test_pdf_utils.py` に soft mask 保持と fallback の回帰テストを追加

今回の追記では、PDF 内部表現が「透過 PNG らしく見えるが、実体は base image + soft mask」であるケースを正しく扱うようにしました。これにより、HTML から WeasyPrint で生成した PDF に貼り付けた透過 PNG が、非可逆圧縮後に黒背景化するリスクを下げています。

### 2026年3月30日追記（アプリ設定 / 効果音）

- ノートブックに `アプリ設定` タブを追加し、起動時とクリーンアップ確認時の効果音を個別トグルで切り替え可能に変更
- 起動時効果音トグルは、起動直後の `open_window.wav` と、Windows 環境でデスクトップ配下の既定フォルダ作成を尋ねる前の `notice.wav` を共通で制御
- クリーンアップ効果音トグルは、入力/出力フォルダのクリーンアップ確認前に鳴る `warning.wav` を制御
- トグル状態は `frontend/config_data/ui_catalogs.json` の `app_settings` セクションへ永続化され、次回起動時にも復元
- `frontend/settings.py` に JSON 読込保存責務を追加し、UI state は `play_startup_sound` / `play_cleanup_sound` として保持

今回の追記では、圧縮機能とは独立したアプリ全体の動作設定を GUI から扱えるように整理しました。特に、毎回起動音やクリーンアップ警告音が不要な環境でも、コード編集なしで振る舞いを固定できるようになっています。

### 2026年3月31日追記（セキュリティと ZIP 運用上限）

- `backend/core/pdf_utils.py` と `backend/core/image_utils.py` で、Ghostscript / pngquant の呼び出しを安全側へ整理
- 外部コマンド呼び出しは shell を使わず引数配列のまま実行し、timeout を追加
- Ghostscript の custom DPI、JPG/PNG 品質、pngquant quality range は安全な範囲へ正規化
- Ghostscript には `-dSAFER` とファイル引数区切り、pngquant には `--` を追加し、オプション解釈のぶれを減らした
- `backend/core/archive_utils.py` で ZIP member の path traversal、絶対パス、Windows ドライブ指定、symlink 相当 entry を拒否
- ZIP 展開には `member数 <= 10000`、`展開後合計サイズ <= 1,000,000,000 bytes` の上限を追加
- `frontend/ui_tkinter_mapper.py` で resize 幅/高さ/長辺と Ghostscript DPI を clamp し、極端値が backend へ流れないように整理
- `tests/unit/test_archive_utils.py`、`tests/unit/test_image_utils.py`、`tests/unit/test_pdf_utils.py`、`tests/unit/test_ui_tkinter_mapper.py`、`tests/integration/test_job_runner.py` に回帰テストを追加

今回の追記では、主に「未信頼入力を ZIP 展開や外部 CLI に通す境界」を硬化しました。OS コマンドインジェクション自体は元々起きにくい構成でしたが、ZIP の危険 member、極端な品質値や DPI、長時間ハングする外部ツール呼び出しに対して、失敗し方を制御できるようにしています。あわせて、ZIP の現実的な運用上限はコード上限の 1 GB ではなく、実サイズ 300 MB から 500 MB 程度を標準目安とする方が安定、という判断を README に明記しました。

### フローチャートなど

こちらのドキュメントを参照してください:

- HTML版: [フロー図、シーケンス図およびクラス図](./flow_sequence_and_class_diagrams.html)
- Markdown版: [flow_sequence_and_class_diagrams.md](./flow_sequence_and_class_diagrams.md)

## ライセンス

このアプリケーションは自由に改変・利用可能です。ご利用環境に応じた依存関係のライセンス条項に従ってください。

## バージョン情報

- バージョン: 1.0.0
  - リリース日: 2025年12月11日
- バージョン: 2.0.0
  - リリース日: 2026年3月5日
  - 主な変更点:
    - PDF圧縮エンジンの選択肢追加（PyMuPDF(非可逆・画像圧縮) + pikepdf(可逆・メタデータ最適化) / Ghostscript）
    - GUIの改善 (タブ表示など)
    - コードベースの大規模リファクタリング
      - フロントエンド/バックエンドの完全分離
      - 起動経路の整理（launcher → frontend.bootstrap → frontend/ui_tkinter）
      - コードベースのクリーンアップとモジュール再配置
      - `backend/core/compressor_utils.py` を責務分割（pdf/image/archive/file_ops/worker/format）し、互換shim化
- バージョン: 2.0.1
  - リリース日: 2026年3月6日
  - 主な変更点:
    - 出力設定に「圧縮対象外のファイルを出力フォルダへコピー」トグルを追加（既定OFF）
    - 未対応拡張子のコピー出力（入力フォルダの相対構造を維持）を追加
    - 圧縮失敗時のフォールバックコピーを追加（トグルON時）
- バージョン: 2.1.0
  - リリース日: 2026年3月6日
  - 主な変更点:
    - ZIP展開時の処理を入力フォルダ直接展開から一時作業領域展開へ変更（入力フォルダ不変を保証）
    - ZIP展開時の出力先を、ZIPファイルの拡張子(.zip)を除いた名前のフォルダ配下に統一し、ZIP内部構造を維持して出力
    - ZIP処理を `ZIP展開してから圧縮` と `ミラー圧縮` の組み合わせで明確化
- バージョン: 2.1.1
  - リリース日: 2026年3月11日
  - 主な変更点:
    - frontend 配下の Pylance 警告を解消するため、型契約ファイル `frontend/ui_contracts.py` を追加
    - `ui_tkinter_mapper.py` の `Any` を除去し、UI状態からDTO変換までの型安全性を改善
    - `ui_tkinter_state.py` / `ui_tkinter_view.py` に明示的な型注釈を追加
    - `tkinterdnd2` 連携を局所型補助へ整理し、可読性と保守性を改善
    - `scripts/tkinter_regression_check.py` による回帰確認を実施し、主要GUIフローの動作継続を確認
    - `frontend/ui_tkinter_controller.py` の mixin 依存を `frontend/ui_contracts.py` の Protocol として明文化し、controller の Pylance 警告を解消
    - `frontend/sound_utils.py` に型注釈と optional pygame の型狭義化を追加し、保守性と可読性を改善
    - `after()` を使う UI 更新経路を helper 化し、controller のスレッド境界処理を整理
    - `Documentation/flow_sequence_and_class_diagrams.md` に `frontend/ui_contracts.py` の現行内容を追記し、型契約の実体を図面ドキュメント側から参照できるよう整理
    - 対象モジュールの Pylance 診断でエラー 0 を確認
    - `frontend.ui_tkinter.App` の生成による起動スモークテストを実施し、初期化が正常終了することを確認
- バージョン: 2.2.1
  - リリース日: 2026年3月15日
  - 主な変更点:
    - pytest の実行プロファイルを `unit` / `integration` / `regression` に整理し、`pyproject.toml` に marker と discovery 設定を追加
    - `tests/conftest.py` と `tests/unit/` を追加し、契約、依存検出、ZIP 展開、画像圧縮、UI DTO マッピングの自動テストを整備
    - `tests/integration/` を追加し、`job_runner` の CSV 出力・ZIP 一時作業領域・フォールバックコピー、および `ui_tkinter_controller` の主要導線を検証可能にした
    - 旧 `scripts/tkinter_regression_check.py` を `tests/regression/test_tkinter_regression.py` へ完全移植し、GUI 回帰を pytest から選択実行できるよう統合
    - `backend/orchestrator/job_runner.py` の CSV 入出力パス連携不具合を修正し、テストで再発防止を追加
    - PyMuPDF の画像再圧縮で、デバッグモードON時に標準出力へ画像 xref ごとの統計を出すようにして、効果が確認できるようにした
    - 設定レイヤを `shared/runtime_paths.py` / `backend/settings.py` / `frontend/settings.py` に分離し、UI の純粋データを `frontend/config_data/ui_catalogs.json` へ移行
- バージョン: 2.3.0
  - リリース日: 2026年3月15日
  - 主な変更点:
    - `compress_pdf_lossy()` を `page.get_image_info(xrefs=True)` ベースへ変更し、実描画画像だけを対象にするよう修正
    - WeasyPrint 系 PDF で先頭ページの負の判定が全ページへ伝播し、後続ページの画像再圧縮を取り逃がす不具合を解消
    - `tests/unit/test_pdf_utils.py` を追加し、xref 一回処理と missing xref / zero bbox の分岐を回帰テスト化
- バージョン: 2.4.0
  - リリース日: 2026年3月16日
  - 主な変更点:
    - ネイティブ PDF 非可逆圧縮で、PDF 内 PNG 系画像を JPEG へ変換せず PNG のまま量子化するよう変更
    - PDF ネイティブ設定の `PNG→JPEG変換` を廃止し、`PNG品質` スライダーを追加
    - `pngquant` 利用時は PDF 用 PNG 品質スライダー値から quality 範囲を自動計算し、未導入時は Pillow の 256 色固定減色へフォールバックするよう整理
    - `CompressionRequest` と worker 配線を `pdf_png_quality` ベースへ移行し、関連 unit/integration テストを更新
- バージョン: 2.5.0
  - リリース日: 2026年3月30日
  - 主な変更点:
    - ネイティブ PDF 非可逆圧縮で、`SMask` を読み取って透過情報を再構成し、soft mask 付き画像を透過付き PNG 経路へ送るよう改善
    - soft mask の抽出または復元に失敗した場合も処理全体は止めず、従来経路へフォールバックしつつ debug stats で追跡可能に整理
    - ノートブックに `アプリ設定` タブを追加し、起動時効果音（`open_window.wav` / `notice.wav`）とクリーンアップ確認時効果音（`warning.wav`）を個別に ON/OFF 可能にした
    - 効果音トグル状態を `frontend/config_data/ui_catalogs.json` の `app_settings` へ保存し、次回起動時にも復元するようにした
- バージョン: 2.5.2
  - リリース日: 2026年4月6日
  - 主な変更点:
    - PDF 埋め込み画像と単体画像ファイルの両経路で、CMYK 画像を ICC プロファイル優先で RGB へ変換する処理を追加
    - ネイティブ PDF 非可逆圧縮の debug stats に `cmyk_converted` を追加し、色空間変換の発生件数を確認可能にした
    - `backend/core/pdf_utils.py` と `backend/core/image_utils.py` の CMYK 変換経路へ自己文書化の Docstring と inline comment を追加
- バージョン: 2.5.1
  - リリース日: 2026年3月31日
  - 主な変更点:
    - Ghostscript / pngquant 呼び出しに timeout、引数正規化、ファイル引数区切りを追加し、安全側の subprocess 実行へ整理
    - ZIP 展開で path traversal、絶対パス、Windows ドライブ指定、symlink 相当 entry を拒否し、member 数と展開後合計サイズの上限を追加
    - UI mapper で resize 値と Ghostscript custom DPI を clamp し、極端値入力が backend へ流れないよう改善
    - unit / integration テストを追加し、ZIP 安全化、外部 CLI 引数ガード、UI clamp 伝播を回帰テスト化

---

2026年3月16日
株式会社京都ダイケンビルサービス
千總本社ビル設備
川﨑　翔
