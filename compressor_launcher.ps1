param(
	[ValidateSet('Run', 'Build')]
	[string]$Mode = 'Run'
)

Set-Location -Path $PSScriptRoot

if (-not (Test-Path ./.venv/Scripts/Activate.ps1)) {
	Write-Error '.venv が見つかりません。先に仮想環境を作成してください。'
	exit 1
}

. ./.venv/Scripts/Activate.ps1

if ($Mode -eq 'Build') {
	python -c "import PyInstaller" 2>$null
	if ($LASTEXITCODE -ne 0) {
		Write-Error 'PyInstaller が未インストールです。`python -m pip install pyinstaller` を実行してください。'
		deactivate
		exit 1
	}

	if (-not (Test-Path ./vendor)) {
		Write-Warning 'vendor/ が見つからないため、system 優先のみの構成でビルドします。bundled fallback は同梱されません。'
	}

	python -m PyInstaller --clean ./compressor_launcher_tkinter.spec
	$exitCode = $LASTEXITCODE
	deactivate
	exit $exitCode
}

python ./compressor_launcher_tkinter.py
$exitCode = $LASTEXITCODE
deactivate
exit $exitCode
