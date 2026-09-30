"""Publica a versão atual do repositório no PythonAnywhere pela API.

Usado pelo GitHub Actions (.github/workflows/deploy.yml) a cada atualização da main:
envia os arquivos alterados, apaga os removidos, recarrega o site e confere /saude.
As migrações do banco rodam sozinhas quando o site recarrega.

Variáveis de ambiente:
  PA_USERNAME   usuário do PythonAnywhere (obrigatória)
  PA_API_TOKEN  token da API — Account > API token (obrigatória)
  PA_HOST       www.pythonanywhere.com (padrão) ou eu.pythonanywhere.com
  PA_DOMAIN     domínio do site (padrão: <usuario>.pythonanywhere.com)
  PA_PROJECT    pasta do projeto (padrão: /home/<usuario>/firstproject)
  BASE_SHA      commit publicado antes; vazio = envia todos os arquivos
  (PA_API_BASE e PA_SITE_URL substituem os endereços — usados só em testes)
"""
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

IGNORAR = (".github/", "tests/")  # não precisam estar no servidor
DEPENDENCIAS = {"requirements.txt"}


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def alteracoes(base):
    """(arquivos a enviar, arquivos a apagar)."""
    if base and set(base) != {"0"}:
        try:
            saida = git("diff", "--name-status", "--no-renames", base, "HEAD")
        except subprocess.CalledProcessError:
            saida = None  # commit base desconhecido: envia tudo
        if saida is not None:
            enviar, apagar = [], []
            for linha in saida.splitlines():
                status, caminho = linha.split("\t", 1)
                (apagar if status == "D" else enviar).append(caminho)
            return enviar, apagar
    return git("ls-files").splitlines(), []


class API:
    def __init__(self, host, usuario, token):
        self.base = os.environ.get("PA_API_BASE") or f"https://{host}/api/v0/user/{usuario}"
        self.token = token

    def chamar(self, metodo, caminho, corpo=None, tipo=None, tentativas=6):
        for tentativa in range(tentativas):
            req = urllib.request.Request(self.base + caminho, data=corpo, method=metodo)
            req.add_header("Authorization", f"Token {self.token}")
            if tipo:
                req.add_header("Content-Type", tipo)
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return resp.status, resp.read()
            except urllib.error.HTTPError as erro:
                if erro.code in (429, 500, 502, 503, 504) and tentativa < tentativas - 1:
                    time.sleep(2 ** tentativa)  # limite de requisições ou instabilidade
                    continue
                return erro.code, erro.read()
            except urllib.error.URLError:
                if tentativa < tentativas - 1:
                    time.sleep(2 ** tentativa)
                    continue
                raise

    def enviar_arquivo(self, destino, conteudo):
        limite = uuid.uuid4().hex
        corpo = (
            f"--{limite}\r\nContent-Disposition: form-data; name=\"content\"; filename=\"f\"\r\n"
            "Content-Type: application/octet-stream\r\n\r\n"
        ).encode() + conteudo + f"\r\n--{limite}--\r\n".encode()
        return self.chamar("POST", f"/files/path{destino}", corpo,
                           f"multipart/form-data; boundary={limite}")


def conferir_site(dominio, tentativas=10):
    for _ in range(tentativas):
        try:
            url = os.environ.get("PA_SITE_URL") or f"https://{dominio}"
            with urllib.request.urlopen(f"{url}/saude", timeout=30) as resp:
                if resp.read().decode().strip() == "ok":
                    return True
        except (urllib.error.URLError, TimeoutError):
            pass
        time.sleep(6)
    return False


def main():
    usuario = os.environ.get("PA_USERNAME", "").strip()
    token = os.environ.get("PA_API_TOKEN", "").strip()
    if not usuario or not token:
        print("::error::Configure os segredos PA_USERNAME e PA_API_TOKEN no GitHub "
              "(Settings > Secrets and variables > Actions).")
        return 1
    host = os.environ.get("PA_HOST") or "www.pythonanywhere.com"
    dominio = os.environ.get("PA_DOMAIN") or f"{usuario}.pythonanywhere.com"
    projeto = (os.environ.get("PA_PROJECT") or f"/home/{usuario}/firstproject").rstrip("/")
    api = API(host, usuario, token)

    enviar, apagar = alteracoes(os.environ.get("BASE_SHA", "").strip())
    enviar = [c for c in enviar if not c.startswith(IGNORAR)]
    apagar = [c for c in apagar if not c.startswith(IGNORAR)]

    if DEPENDENCIAS & set(enviar) and os.environ.get("BASE_SHA", "").strip():
        print("::error::Esta atualização muda as dependências (requirements.txt), que precisam "
              "ser instaladas no servidor. Publique pelo console do PythonAnywhere (uma vez): "
              "cd ~/firstproject && git fetch && git reset --hard origin/main && "
              "bash deploy/pythonanywhere_setup.sh — e depois Reload na aba Web.")
        return 1

    if not enviar and not apagar:
        print("Nenhum arquivo do sistema mudou; nada a publicar.")
        return 0

    print(f"Enviando {len(enviar)} arquivo(s) e removendo {len(apagar)} em {dominio}…")
    for caminho in enviar:
        with open(caminho, "rb") as f:
            status, corpo = api.enviar_arquivo(f"{projeto}/{caminho}", f.read())
        if status not in (200, 201):
            print(f"::error::Falha ao enviar {caminho}: HTTP {status} {corpo[:300]!r}")
            return 1
        print(f"  enviado  {caminho}")
    for caminho in apagar:
        status, corpo = api.chamar("DELETE", f"/files/path{projeto}/{caminho}")
        if status not in (200, 204, 404):
            print(f"::error::Falha ao remover {caminho}: HTTP {status} {corpo[:300]!r}")
            return 1
        print(f"  removido {caminho}")

    status, corpo = api.chamar("POST", f"/webapps/{dominio}/reload/")
    if status != 200:
        print(f"::error::Falha ao recarregar o site: HTTP {status} {corpo[:300]!r}")
        return 1
    print("Site recarregado; conferindo se voltou ao ar…")
    if not conferir_site(dominio):
        print(f"::error::O site não respondeu em https://{dominio}/saude após recarregar. "
              "Veja o Error log na aba Web do PythonAnywhere.")
        return 1
    print(f"Publicado com sucesso: https://{dominio}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
