$ErrorActionPreference = "Stop"
$root = Split-Path -Parent $MyInvocation.MyCommand.Path

if (-not (Test-Path "$root/backend/.venv")) {
  py -3 -m venv "$root/backend/.venv"
}

& "$root/backend/.venv/Scripts/Activate.ps1"
python -m pip install --upgrade pip
pip install -r "$root/backend/requirements.txt"
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root/backend'; uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"

cd "$root/frontend"
npm install
Start-Process powershell -ArgumentList "-NoExit", "-Command", "cd '$root/frontend'; npm run dev -- --host 0.0.0.0 --port 5173"
Write-Host "Open http://localhost:5173"
