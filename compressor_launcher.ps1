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

function Get-ProjectVersion {
	param(
		[string]$ProjectRoot
	)

	$versionScript = Join-Path $ProjectRoot 'scripts/get_version.py'
	$version = (& python $versionScript).Trim()
	if ([string]::IsNullOrWhiteSpace($version)) {
		throw 'pyproject.toml からバージョン番号を取得できませんでした。'
	}

	return $version
}

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

	python -m PyInstaller --clean --noconfirm ./compressor_launcher_tkinter.spec
	if ($LASTEXITCODE -ne 0) {
		$exitCode = $LASTEXITCODE
		deactivate
		exit $exitCode
	}

	$installerScript = Join-Path $PSScriptRoot 'pjp_compressor.iss'
	if (-not (Test-Path $installerScript)) {
		Write-Error 'pjp_compressor.iss が見つかりません。'
		deactivate
		exit 1
	}

	$innoSetupCompiler = Get-Command ISCC.exe -ErrorAction SilentlyContinue | Select-Object -First 1
	if (-not $innoSetupCompiler) {
		$innoSetupCompiler = Get-Command iscc -ErrorAction SilentlyContinue | Select-Object -First 1
	}
	if (-not $innoSetupCompiler) {
		Write-Error 'Inno Setup Compiler (ISCC.exe) が見つかりません。Inno Setup をインストールしてから再実行してください。'
		deactivate
		exit 1
	}

	$projectVersion = Get-ProjectVersion -ProjectRoot $PSScriptRoot
	& $innoSetupCompiler.Path "/DMyAppVersion=$projectVersion" $installerScript
	$exitCode = $LASTEXITCODE
	deactivate
	exit $exitCode
}

python ./compressor_launcher_tkinter.py
$exitCode = $LASTEXITCODE
deactivate
exit $exitCode
