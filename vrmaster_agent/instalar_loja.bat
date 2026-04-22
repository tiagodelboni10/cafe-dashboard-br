@echo off
REM =====================================================================
REM  Instalacao do Agente NFe no PC da Loja
REM  Uso: rodar como Administrador
REM  Pre-requisitos: Python 3.11+ e Git for Windows instalados
REM =====================================================================
setlocal EnableDelayedExpansion
echo.
echo === Agente NFe - Instalacao no PC da Loja ===
echo.

REM --- 1. Verificar Python ---
where python >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Python nao instalado. Baixe em https://www.python.org/downloads/
    echo        Durante a instalacao marque "Add Python to PATH".
    pause
    exit /b 1
)
python --version

REM --- 2. Verificar Git ---
where git >nul 2>&1
if errorlevel 1 (
    echo [ERRO] Git nao instalado. Baixe em https://git-scm.com/download/win
    pause
    exit /b 1
)
git --version

REM --- 3. Clonar ou atualizar repositorio ---
if not exist "C:\Cafe" (
    echo Clonando repositorio em C:\Cafe...
    cd /d C:\
    git clone https://github.com/tiagodelboni10/cafe-dashboard-br.git Cafe
) else (
    echo C:\Cafe ja existe, atualizando...
    cd /d C:\Cafe
    git pull
)

REM --- 4. Criar venv e instalar dependencias ---
cd /d C:\Cafe
if not exist ".venv" (
    echo Criando ambiente virtual .venv...
    python -m venv .venv
)
echo Instalando dependencias...
.venv\Scripts\python.exe -m pip install --upgrade pip --quiet
.venv\Scripts\python.exe -m pip install -r vrmaster_agent\requirements.txt

REM --- 5. Criar config.py se nao existir ---
if not exist "C:\Cafe\vrmaster_agent\config.py" (
    echo Criando config.py padrao...
    (
    echo import os
    echo.
    echo DB_HOST = "177.71.35.119"
    echo DB_PORT = 8745
    echo DB_NAME = "vr"
    echo DB_USER = "postgres"
    echo DB_PASS = "VrPost@Server"
    echo.
    echo BASE_DIR = os.path.dirname^(os.path.abspath^(__file__^)^)
    echo EXPORT_DIR = os.path.join^(BASE_DIR, "exports"^)
    echo REPORTS_DIR = os.path.join^(BASE_DIR, "reports"^)
    echo LOGS_DIR = os.path.join^(BASE_DIR, "logs"^)
    echo os.makedirs^(EXPORT_DIR, exist_ok=True^)
    echo os.makedirs^(REPORTS_DIR, exist_ok=True^)
    echo os.makedirs^(LOGS_DIR, exist_ok=True^)
    echo.
    echo TOLERANCIA_MARGEM = 2.0
    echo ID_LOJA = 1
    echo GRUPO_WHATSAPP = "MERKAL ADM"
    echo NUMERO_WHATSAPP = "5527999044729"
    ) > C:\Cafe\vrmaster_agent\config.py
    echo Config padrao criado em C:\Cafe\vrmaster_agent\config.py
)

REM --- 6. Reescrever os .bat com caminho certo de C:\Cafe ---
> C:\Cafe\vrmaster_agent\listener_nfe.bat (
    echo @echo off
    echo cd /d "%%~dp0"
    echo "C:\Cafe\.venv\Scripts\python.exe" listener_nfe.py
)
> C:\Cafe\vrmaster_agent\agente_nfe.bat (
    echo @echo off
    echo cd /d "%%~dp0"
    echo "C:\Cafe\.venv\Scripts\pythonw.exe" agente_nfe.py
)

REM --- 7. Agendar listener no Startup do Windows ---
powershell -Command ^
    "$startup = [Environment]::GetFolderPath('Startup'); " ^
    "$target = 'C:\Cafe\vrmaster_agent\listener_nfe.bat'; " ^
    "$link = Join-Path $startup 'Listener NFe Merkal.lnk'; " ^
    "$ws = New-Object -ComObject WScript.Shell; " ^
    "$sc = $ws.CreateShortcut($link); " ^
    "$sc.TargetPath = $target; " ^
    "$sc.WorkingDirectory = (Split-Path $target); " ^
    "$sc.WindowStyle = 7; " ^
    "$sc.Save(); " ^
    "Write-Output ('Shortcut criado em: ' + $link)"

REM --- 8. Agendar agente NFe no Task Scheduler (1 min) ---
schtasks /create /tn "Agente VR Master - Agente NFe" ^
  /tr "C:\Cafe\.venv\Scripts\pythonw.exe C:\Cafe\vrmaster_agent\agente_nfe.py" ^
  /sc minute /mo 1 /f

echo.
echo ================================================
echo  INSTALACAO CONCLUIDA
echo ================================================
echo.
echo Proximos passos manuais:
echo   1. Rodar o listener UMA vez pra escanear o QR do WhatsApp Web:
echo        C:\Cafe\vrmaster_agent\listener_nfe.bat
echo      (depois de conectado, feche a janela - Startup vai reabrir no proximo logon)
echo.
echo   2. Abrir e maximizar o VR Master, deixar logado no usuario de servico.
echo.
echo   3. Reiniciar o PC (opcional, so pra garantir que o Startup do listener funciona).
echo.
echo Log da tarefa agendada:
schtasks /query /tn "Agente VR Master - Agente NFe" /fo LIST | findstr /i "Status Hora"
echo.
pause
