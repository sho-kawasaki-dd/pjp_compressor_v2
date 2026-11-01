<#
    このスクリプトは、プロジェクトルート直下の vendor フォルダーを ZIP にまとめる。
    x264-only の監査済みビルドが用意されるまで、ffmpeg-windows は ZIP に含めない。

    実行時のカレントディレクトリに依存しないよう、スクリプト自身の配置場所を基準に
    vendor フォルダーと出力先 ZIP を決定する。
#>
Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$rootPath = Split-Path -Parent $MyInvocation.MyCommand.Path
$vendorPath = Join-Path $rootPath 'vendor'
$archivePath = Join-Path $rootPath 'vendor.zip'

if (-not (Test-Path -LiteralPath $vendorPath -PathType Container)) {
    throw 'vendor フォルダーが見つかりません。プロジェクトルートで実行してください。'
}

if (Test-Path -LiteralPath $archivePath) {
    Remove-Item -LiteralPath $archivePath -Force
}

Add-Type -AssemblyName System.IO.Compression
Add-Type -AssemblyName System.IO.Compression.FileSystem
$vendorUri = [Uri]::new(($vendorPath.TrimEnd('\') + '\'))
$files = Get-ChildItem -LiteralPath $vendorPath -File -Recurse | Where-Object {
    $relative = [Uri]::UnescapeDataString($vendorUri.MakeRelativeUri([Uri]::new($_.FullName)).ToString())
    ($relative -split '[\\/]')[0] -ne 'ffmpeg-windows'
}
if (-not $files) {
    throw 'FFmpeg を除外した後に ZIP 対象の vendor ファイルがありません。'
}

$stream = [System.IO.File]::Open($archivePath, [System.IO.FileMode]::Create)
$archive = [System.IO.Compression.ZipArchive]::new($stream, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($file in $files) {
        $relative = [Uri]::UnescapeDataString($vendorUri.MakeRelativeUri([Uri]::new($file.FullName)).ToString())
        $entryName = "vendor/$($relative.Replace('\', '/'))"
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile(
            $archive,
            $file.FullName,
            $entryName,
            [System.IO.Compression.CompressionLevel]::Optimal
        ) | Out-Null
    }
}
finally {
    $archive.Dispose()
}

Write-Host "ffmpeg-windows を除外した vendor.zip を作成しました: $archivePath"