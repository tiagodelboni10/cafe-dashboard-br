# Instalação no PC da Loja — Agente NF-e

PC dedicado pra processar entrada de NF-e automaticamente.

## Pré-requisitos (instalar uma vez)

1. **Python 3.11+**
   https://www.python.org/downloads/ → marcar "Add Python to PATH" no instalador.
   Confirmar: `python --version`

2. **Git for Windows**
   https://git-scm.com/download/win
   Confirmar: `git --version`

3. **Chrome** (pro listener do WhatsApp Web) — normalmente já tem.

4. **VR Master aberto e logado** — deixar sempre rodando, maximizado.

## Passos de instalação

Abrir **PowerShell** ou **CMD como Administrador** e rodar:

```powershell
# 1. Clonar o repositorio
cd C:\
git clone https://github.com/tiagodelboni10/cafe-dashboard-br.git Cafe
cd C:\Cafe\vrmaster_agent

# 2. Criar ambiente virtual e instalar dependencias
cd C:\Cafe
python -m venv .venv
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r vrmaster_agent\requirements.txt

# 3. Criar config.py (copiar do PC de casa OU digitar manualmente)
notepad C:\Cafe\vrmaster_agent\config.py
```

**Conteudo do `config.py`:**

```python
import os

DB_HOST = "177.71.35.119"
DB_PORT = 8745
DB_NAME = "vr"
DB_USER = "postgres"
DB_PASS = "VrPost@Server"

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
EXPORT_DIR = os.path.join(BASE_DIR, "exports")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
LOGS_DIR = os.path.join(BASE_DIR, "logs")

os.makedirs(EXPORT_DIR, exist_ok=True)
os.makedirs(REPORTS_DIR, exist_ok=True)
os.makedirs(LOGS_DIR, exist_ok=True)

TOLERANCIA_MARGEM = 2.0
ID_LOJA = 1
GRUPO_WHATSAPP = "MERKAL ADM"
NUMERO_WHATSAPP = "5527999044729"
```

## Primeira execução — WhatsApp Web QR code

```powershell
cd C:\Cafe\vrmaster_agent
..\.venv\Scripts\python.exe listener_nfe.py
```

Vai abrir Chrome com WhatsApp Web. Escaneie o QR pelo celular:
**WhatsApp → Menu (⋮) → Dispositivos conectados → Conectar dispositivo**.

Depois que conectar e o log mostrar `Listener ativo. Polling a cada 20s.`, **deixe rodando** (ou feche esse terminal e agende abaixo).

## Agendar no Task Scheduler

```powershell
# Listener WhatsApp — inicia no logon do Windows
$startup = [Environment]::GetFolderPath('Startup')
$target = "C:\Cafe\vrmaster_agent\listener_nfe.bat"
$link = Join-Path $startup 'Listener NFe Merkal.lnk'
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut($link)
$sc.TargetPath = $target
$sc.WorkingDirectory = (Split-Path $target)
$sc.WindowStyle = 7
$sc.Save()

# Agente NFe — roda a cada 1 minuto
schtasks /create /tn "Agente VR Master - Agente NFe" `
  /tr "C:\Cafe\.venv\Scripts\pythonw.exe C:\Cafe\vrmaster_agent\agente_nfe.py" `
  /sc minute /mo 1 /f
```

## Ajustar caminhos dos .bat

Edite **C:\Cafe\vrmaster_agent\listener_nfe.bat** pra apontar pra `.venv` correto:

```bat
@echo off
cd /d "%~dp0"
"C:\Cafe\.venv\Scripts\python.exe" listener_nfe.py
```

E **C:\Cafe\vrmaster_agent\agente_nfe.bat**:

```bat
@echo off
cd /d "%~dp0"
"C:\Cafe\.venv\Scripts\pythonw.exe" agente_nfe.py
```

## Verificação final

1. **Listener rodando**: `Get-Process python, pythonw` deve mostrar 2 processos (pelo menos).
2. **Task Scheduler**: abrir `taskschd.msc` → ver tarefa "Agente VR Master - Agente NFe" habilitada.
3. **VR Master**: aberto, maximizado, logado com usuário que tem permissão de Conferir/Carregar.
4. **Rede**: `Test-NetConnection 192.168.0.250 -Port 9010` → ok (se precisar pro cliente fiscal futuro).

## Como funciona

- **06h–20h (Modo C3 — diurno semi-auto):**
  Colaborador manda `OK 6042` no grupo Merkal NOTAS → Listener captura → Agente abre Repositório no VR, filtra a nota 6042, faz Conferir automático, **abre o dialog Carregar com o Tipo preenchido**. Operador só clica **Carregar** (1 clique).

- **20h–06h (Modo D — noturno full-auto):**
  Agente processa tudo que ficou acumulado. Se der erro ou dialog inesperado (divergência grave, etc.), **pula a nota** e manda aviso no grupo pra tratar manualmente no dia seguinte.

- **Respostas no grupo**: o listener envia mensagens de confirmação/erro no próprio grupo Merkal NOTAS via Selenium (não precisa calibração de pixel).

## Logs pra debug

- `C:\Cafe\vrmaster_agent\logs\listener_nfe_YYYYMMDD.log`
- `C:\Cafe\vrmaster_agent\logs\agente_nfe_YYYYMMDD.log`
- `C:\Cafe\vrmaster_agent\nfe_fila\` — fila (OKs aguardando processamento)
- `C:\Cafe\vrmaster_agent\nfe_processadas\` — concluídas
- `C:\Cafe\vrmaster_agent\nfe_erros\` — falhas
- `C:\Cafe\vrmaster_agent\nfe_respostas\` — respostas WhatsApp aguardando envio

## Dúvidas / problemas

Me chama com o trecho do log em `logs/agente_nfe_YYYYMMDD.log` e a gente ajusta.
