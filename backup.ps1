<#
    このスクリプトは、プロジェクトルート配下のうち .gitignore で無視されないファイルと、
    dist/ 配下を除いたファイルをタイムスタンプ付き ZIP としてバックアップする。

    無視判定は PowerShell 側で再実装せず、Git の `ls-files --exclude-standard` に委ねることで、
    `.gitignore`・`.git/info/exclude`・グローバル ignore を含む Git 標準の判定結果に合わせる。
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# スクリプト自身が置かれているフォルダをプロジェクトルートとして扱う。
# 実行時のカレントディレクトリに依存させないため、呼び出し元がどこでも同じ結果になる。
$rootPath = Split-Path -Parent $MyInvocation.MyCommand.Path

# バックアップファイル名は作成日時を含め、連続実行しても重複しにくい命名にする。
$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$appName = 'pjp_compressor_v2.6.0'
$archiveName = "${appName}_$timestamp.zip"
$archivePath = Join-Path $rootPath $archiveName

# ZIP に含めるファイル群を一度テンポラリ領域へ複製してから圧縮する。
# こうすることで、選別済みファイルだけを元の相対パス構成のまま安全にアーカイブできる。
$stagingPath = Join-Path ([System.IO.Path]::GetTempPath()) ([System.Guid]::NewGuid().ToString())

try {
    # 無視判定を Git に委ねる設計なので、先に git コマンドの存在を確認する。
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        throw 'git コマンドが見つかりません。Git をインストールしてから実行してください。'
    }

    # Git 管理下のファイルと、未追跡だが ignore されていないファイルを収集する。
    # これにより .gitignore 対象を除外した「実際に残したいファイル群」をそのまま取得できる。
    $files = New-Object 'System.Collections.Generic.List[string]'
    foreach ($gitTrackedPath in @(git -C $rootPath ls-files --cached --others --exclude-standard)) {
        if (-not [string]::IsNullOrWhiteSpace($gitTrackedPath)) {
            if ($gitTrackedPath -eq 'dist' -or $gitTrackedPath.StartsWith('dist/')) {
                continue
            }

            [void]$files.Add([string]$gitTrackedPath)
        }
    }

    if (-not $files -or $files.Count -eq 0) {
        throw 'バックアップ対象のファイルが見つかりませんでした。'
    }

    # ステージング用ディレクトリを新規作成し、ここへ必要なファイルだけを並べる。
    New-Item -ItemType Directory -Path $stagingPath | Out-Null

    # Git 管理対象と未追跡分で同じファイルが重複する可能性があるため、
    # コピー済みパスを集合で管理して二重コピーを防ぐ。
    $copiedPaths = New-Object 'System.Collections.Generic.HashSet[string]' ([System.StringComparer]::OrdinalIgnoreCase)

    # Git が返す相対パスを基準に、元のディレクトリ構造を維持したまま複製する。
    foreach ($relativePath in $files) {
        # 念のため空行や空文字が混ざっていた場合は無視する。
        if ([string]::IsNullOrWhiteSpace($relativePath)) {
            continue
        }

        if (-not $copiedPaths.Add($relativePath)) {
            continue
        }

        $sourcePath = Join-Path $rootPath $relativePath
        # Git の出力に含まれていても、特殊な状況で通常ファイルとして存在しないものは除外する。
        # バックアップ対象はファイルのみとし、ディレクトリや不整合な項目は扱わない。
        if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) {
            continue
        }

        $destinationPath = Join-Path $stagingPath $relativePath
        $destinationDirectory = Split-Path -Parent $destinationPath
        # 深い階層のファイルも複製できるよう、コピー前に必要な親ディレクトリを作成する。
        if ($destinationDirectory -and -not (Test-Path -LiteralPath $destinationDirectory)) {
            New-Item -ItemType Directory -Path $destinationDirectory -Force | Out-Null
        }

        # LiteralPath を使い、角括弧などを含むファイル名もワイルドカード解釈されないようにする。
        Copy-Item -LiteralPath $sourcePath -Destination $destinationPath -Force
    }

    # .NET の ZIP API を利用して、ステージング済みファイル群をルート直下へ 1 つのアーカイブとして保存する。
    Add-Type -AssemblyName System.IO.Compression.FileSystem
    [System.IO.Compression.ZipFile]::CreateFromDirectory($stagingPath, $archivePath)

    Write-Host "バックアップを作成しました: $archivePath"
}
finally {
    # 途中で失敗してもテンポラリ領域を残さないよう、後始末は finally で必ず実行する。
    if (Test-Path -LiteralPath $stagingPath) {
        Remove-Item -LiteralPath $stagingPath -Recurse -Force
    }
}