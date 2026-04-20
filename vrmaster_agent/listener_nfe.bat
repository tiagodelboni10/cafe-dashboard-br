@echo off
REM Listener do WhatsApp Merkal NOTAS - Selenium + Chrome.
REM Fica rodando em loop. Primeira execucao abre janela do Chrome para QR.
cd /d "%~dp0"
"C:\Users\Tiago\Downloads\Cafe\.venv\Scripts\python.exe" listener_nfe.py
