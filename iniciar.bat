@echo off
REM Inicia o Controle de Rotina no Windows (duplo clique).
cd /d "%~dp0"
if not exist .venv (
  echo Preparando o ambiente pela primeira vez...
  python -m venv .venv || (echo Python nao encontrado. Instale em https://www.python.org/downloads/ & pause & exit /b 1)
)
call .venv\Scripts\activate.bat
pip install -q -r requirements.txt
python serve.py
pause
