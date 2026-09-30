#!/usr/bin/env sh
# Inicia o Controle de Rotina no Linux/macOS.
cd "$(dirname "$0")"
[ -d .venv ] || python3 -m venv .venv
. .venv/bin/activate
pip install -q -r requirements.txt
python serve.py
