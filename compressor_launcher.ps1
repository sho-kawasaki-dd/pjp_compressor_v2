Set-Location -Path $PSScriptRoot
./.venv/Scripts/activate
python ./compressor_launcher.py
deactivate
