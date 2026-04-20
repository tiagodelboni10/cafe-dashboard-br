@echo off
REM Envia o pedido mais recente baixado pelo dashboard para o VR Master
cd /d "%~dp0"
echo.
echo =====================================================
echo  Enviando pedido para VR Master
echo =====================================================
echo.
"C:\Users\Tiago\Downloads\Cafe\.venv\Scripts\python.exe" enviar_pedido.py
echo.
pause
