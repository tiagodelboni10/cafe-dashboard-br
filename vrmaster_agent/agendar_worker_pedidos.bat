@echo off
echo Agendando Worker de Pedidos VR (a cada 1 minuto)
echo.
schtasks /create /tn "Agente VR Master - Worker Pedidos" /tr "C:\Users\Tiago\Downloads\Cafe\vrmaster_agent\worker_pedidos.bat" /sc minute /mo 1 /f
echo.
schtasks /query /tn "Agente VR Master - Worker Pedidos" /fo LIST
pause
