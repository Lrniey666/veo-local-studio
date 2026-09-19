cd "$PSScriptRoot\.."

if (!(Test-Path ".venv")) {
  py -3 -m venv .venv
}

.\.venv\Scripts\Activate.ps1
pip install --upgrade pip
pip install -r requirements.txt
pip install pyinstaller

pyinstaller --noconfirm --clean --name "VeoLocalStudio" --onefile `
  --add-data "assets;assets" `
  launcher.py

Write-Host "EXE built at dist\VeoLocalStudio.exe"
