"""Publica a versão atual do repositório no PythonAnywhere pela API.

Usado pelo GitHub Actions (.github/workflows/deploy.yml) a cada atualização da main.
O servidor guarda em `.publicado` o commit da última publicação; o script envia só o que
mudou desde ele (ou tudo, se não souber), apaga os arquivos removidos, recarrega o site e
confere /saude. As migrações do banco rodam sozinhas quando o site recarrega.

Variáveis de ambiente:
  PA_USERNAME   usuário do PythonAnywhere (obrigatória)
  PA_API_TOKEN  token da API — Account > API token (obrigatória)
  PA_HOST       www.pythonanywhere.com (padrão) ou eu.pythonanywhere.com
  PA_DOMAIN     domínio do site (padrão: <usuario>.pythonanywhere.com)
  PA_PROJECT    pasta do projeto (padrão: /home/<usuario>/firstproject)
  PUBLICAR_TUDO=1  ignora o `.publicado` e envia todos os arquivos
  (PA_API_BASE e PA_SITE_URL substituem os endereços — usados só em testes)
"""
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid

IGNORAR = (".github/", "tests/")  # não precisam estar no servidor
MARCADOR = ".publicado"


def git(*args):
    return subprocess.run(["git", *args], check=True, capture_output=True, text=True).stdout


def alteracoes(base):
    """(arquivos a enviar, arquivos a apagar) desde o commit `base`, ou tudo se não houver."""
    if base:
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
    # A API do PythonAnywhere limita as requisições por minuto: espaça as chamadas.
    INTERVALO = float(os.environ.get("PA_INTERVALO", "1.6"))

    def __init__(self, host, usuario, token):
        self.base = os.environ.get("PA_API_BASE") or f"https://{host}/api/v0/user/{usuario}"
        self.token = token
        self._ultima = 0.0

    def chamar(self, metodo, caminho, corpo=None, tipo=None, tentativas=8):
        for tentativa in range(tentativas):
            espera = self.INTERVALO - (time.monotonic() - self._ultima)
            if espera > 0:
                time.sleep(espera)
            self._ultima = time.monotonic()
            req = urllib.request.Request(self.base + caminho, data=corpo, method=metodo)
            req.add_header("Authorization", f"Token {self.token}")
            if tipo:
                req.add_header("Content-Type", tipo)
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    return resp.status, resp.read()
            except urllib.error.HTTPError as erro:
                resposta = erro.read()
                if erro.code in (429, 500, 502, 503, 504) and tentativa < tentativas - 1:
                    time.sleep(self._tempo_espera(erro, resposta, tentativa))
                    continue
                return erro.code, resposta
            except urllib.error.URLError:
                if tentativa < tentativas - 1:
                    time.sleep(2 ** tentativa)
                    continue
                raise

    @staticmethod
    def _tempo_espera(erro, resposta, tentativa):
        """Segundos a esperar: o que a API pedir (Retry-After ou mensagem) ou espera crescente."""
        pedido = erro.headers.get("Retry-After") if erro.headers else None
        achado = re.search(rb"available in (\d+) second", resposta or b"")
        for valor in (pedido, achado.group(1) if achado else None):
            try:
                return int(valor) + 1
            except (TypeError, ValueError):
                continue
        return min(2 ** tentativa, 30)

    def ler_arquivo(self, caminho):
        status, corpo = self.chamar("GET", f"/files/path{caminho}")
        return corpo if status == 200 else None

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

    # Dependências: o requirements.txt do servidor precisa ser igual ao do repositório.
    with open("requirements.txt", "rb") as f:
        requisitos = f.read()
    no_servidor = api.ler_arquivo(f"{projeto}/requirements.txt")
    if no_servidor is None:
        print(f"::error::Projeto não encontrado em {projeto} no PythonAnywhere. Faça a "
              "instalação inicial pelo console (veja o README).")
        return 1
    if no_servidor.strip() != requisitos.strip():
        print("::error::Esta atualização muda as dependências (requirements.txt), que precisam "
              "ser instaladas no servidor. Publique pelo console do PythonAnywhere (uma vez): "
              "cd ~/firstproject && git fetch && git reset --hard origin/main && "
              "bash deploy/pythonanywhere_setup.sh — e depois Reload na aba Web.")
        return 1

    marcador = None if os.environ.get("PUBLICAR_TUDO") == "1" else api.ler_arquivo(
        f"{projeto}/{MARCADOR}")
    base = marcador.decode().strip() if marcador else ""
    print(f"Versão no servidor: {base[:7] or 'desconhecida (envia tudo)'}; "
          f"publicando: {git('rev-parse', 'HEAD').strip()[:7]}")
    enviar, apagar = alteracoes(base)
    enviar = [c for c in enviar if not c.startswith(IGNORAR)]
    apagar = [c for c in apagar if not c.startswith(IGNORAR)]

    if not enviar and not apagar:
        print("O servidor já está na versão atual; nada a publicar.")
        return 0

    print(f"Enviando {len(enviar)} arquivo(s) e removendo {len(apagar)} em {dominio}…")
    for caminho in enviar:
        with open(caminho, "rb") as f:
            status, corpo = api.enviar_arquivo(f"{projeto}/{caminho}", f.read())
        if not 200 <= status < 300:
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
    if not 200 <= status < 300:
        print(f"::error::Falha ao recarregar o site: HTTP {status} {corpo[:300]!r}")
        return 1
    print("Site recarregado; conferindo se voltou ao ar…")
    if not conferir_site(dominio):
        print(f"::error::O site não respondeu em https://{dominio}/saude após recarregar. "
              "Veja o Error log na aba Web do PythonAnywhere.")
        return 1
    api.enviar_arquivo(f"{projeto}/{MARCADOR}", git("rev-parse", "HEAD").encode())
    print(f"Publicado com sucesso: https://{dominio}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
