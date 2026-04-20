@echo off
REM Worker que puxa pedidos da nuvem e cria no VR Master. Roda a cada 1 min.
cd /d "%~dp0"
"C:\Users\Tiago\Downloads\Cafe\.venv\Scripts\python.exe" worker_pedidos.py >> "logs\worker_pedidos_exec.log" 2>&1
