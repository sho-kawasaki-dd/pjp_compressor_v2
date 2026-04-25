<#
    このスクリプトは、プロジェクトルート直下の vendor フォルダーを ZIP にまとめる。

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

Compress-Archive -LiteralPath $vendorPath -DestinationPath $archivePath

Write-Host "vendor.zip を作成しました: $archivePath"