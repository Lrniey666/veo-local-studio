@echo off
cd /d "%~dp0\.."

REM 若 .venv 存在但 python.exe 壞掉，自動重建
if exist .venv (
  .venv\Scripts\python.exe --version >nul 2>&1
  if errorlevel 1 (
    echo [警告] 偵測到損壞的虛擬環境，正在重建...
    rmdir /s /q .venv
  )
)

if not exist .venv (
  echo [建立] 正在建立虛擬環境...
  python -m venv .venv
  if errorlevel 1 (
    py -3 -m venv .venv
  )
)

call .venv\Scripts\activate
.venv\Scripts\python.exe -m pip install --upgrade pip -q
.venv\Scripts\python.exe -m pip install -r requirements.txt -q

REM 自動執行資料庫遷移（幂等，不會重複新增）
.venv\Scripts\python.exe scripts\migrate_db.py

python launcher.py
