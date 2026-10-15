@echo off
setlocal

if not exist backend\.venv (
  py -3 -m venv backend\.venv
)

call backend\.venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r backend\requirements.txt
start "Backend" cmd /k "cd /d %~dp0backend && uvicorn app.main:app --reload --host 0.0.0.0 --port 8000"

cd /d %~dp0frontend
call npm install
start "Frontend" cmd /k "cd /d %~dp0frontend && npm run dev -- --host 0.0.0.0 --port 5173"

echo Open http://localhost:5173 in your browser.
