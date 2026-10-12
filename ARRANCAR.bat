@echo off
title Dinero Público — Contratos Murcia
cd /d "%~dp0backend"
echo Arrancando servidor...
start "" http://127.0.0.1:8000
python app.py
pause
