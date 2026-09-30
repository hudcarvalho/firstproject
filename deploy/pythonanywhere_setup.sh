#!/usr/bin/env bash
# Instala/atualiza o Controle de Rotina no PythonAnywhere.
# Uso (no console Bash do PythonAnywhere, dentro da pasta do projeto):
#     bash deploy/pythonanywhere_setup.sh
# Pode ser executado de novo para atualizar depois de um "git pull".
set -euo pipefail

PROJETO="$(cd "$(dirname "$0")/.." && pwd)"
WSGI_DIR="${WSGI_DIR:-/var/www}"
cd "$PROJETO"

echo "==> Projeto em $PROJETO"

# 1. Python: usa o mesmo do ambiente já criado ou o mais novo disponível.
if [ -x .venv/bin/python ]; then
  PY=".venv/bin/python"
else
  PY=""
  for v in python3.13 python3.12 python3.11 python3.10; do
    if command -v "$v" >/dev/null 2>&1; then PY="$v"; break; fi
  done
  [ -n "$PY" ] || { echo "Nenhum Python 3.10+ encontrado."; exit 1; }
  echo "==> Criando ambiente virtual com $PY"
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate
VERSAO="$(python -c 'import sys; print(f"{sys.version_info[0]}.{sys.version_info[1]}")')"

echo "==> Instalando dependências (pode levar alguns minutos)"
pip install -q --upgrade pip
pip install -q -r requirements.txt

echo "==> Preparando o banco de dados"
python -c "from app import create_app; create_app()"

# 2. Administrador: criado aqui, antes de o site ir ao ar.
TEM_USUARIO="$(python -c "
from app import create_app
from app.models import Usuario
app = create_app()
with app.app_context():
    print(1 if Usuario.query.first() else 0)
" 2>/dev/null | tail -1)"
if [ "$TEM_USUARIO" = "0" ]; then
  echo
  echo "==> Crie agora o usuário ADMINISTRADOR do sistema"
  until flask --app run criar-admin; do
    echo "Tente novamente."
  done
else
  echo "==> Já existe usuário cadastrado; mantendo."
fi

# 3. Arquivo WSGI do site.
CONTEUDO_WSGI="import os
import sys

caminho = \"$PROJETO\"
if caminho not in sys.path:
    sys.path.insert(0, caminho)
os.chdir(caminho)
os.environ[\"COOKIE_SECURE\"] = \"1\"

from run import app as application  # noqa: E402
"
shopt -s nullglob
arquivos=("$WSGI_DIR"/*_wsgi.py)
if [ "${#arquivos[@]}" -eq 1 ]; then
  WSGI="${arquivos[0]}"
  cp "$WSGI" "$WSGI.bak"
  printf '%s' "$CONTEUDO_WSGI" > "$WSGI"
  echo "==> Arquivo WSGI configurado: $WSGI"
  WSGI_OK=1
else
  printf '%s' "$CONTEUDO_WSGI" > deploy/wsgi_pythonanywhere.py
  echo "==> Site ainda não criado na aba Web (ou há mais de um)."
  echo "    Conteúdo do WSGI salvo em deploy/wsgi_pythonanywhere.py"
  WSGI_OK=0
fi

cat <<FIM

================================================================
 Pronto! Agora, na aba "Web" do PythonAnywhere:
================================================================
FIM
if [ "$WSGI_OK" = "0" ]; then
  cat <<FIM
 1. Add a new web app -> Manual configuration -> Python $VERSAO
 2. Rode este script de novo:  bash deploy/pythonanywhere_setup.sh
FIM
else
  cat <<FIM
 Confira (só na primeira vez):
   - Python version ...... $VERSAO
   - Source code ......... $PROJETO
   - Virtualenv .......... $PROJETO/.venv
   - Static files ........ URL /static/  ->  $PROJETO/app/static
   - Force HTTPS ......... ligado
 Depois clique no botão verde "Reload".

 Lembre: renove o site todo mês na aba Web (botão de estender o prazo).
 Backup: baixe $PROJETO/instance/controle.db pela aba Files.
FIM
fi
