"""Servidor de produção (Waitress) — use para a equipe acessar pela rede ou na hospedagem.

    python serve.py

Variáveis de ambiente opcionais: HOST (padrão 0.0.0.0), PORT (padrão 8000),
DATABASE_URL, SECRET_KEY, COOKIE_SECURE=1 (se houver HTTPS), PROXY_FIX=1 (atrás de proxy).
"""
import os
import socket

from waitress import serve

from app import create_app


def enderecos_locais():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("10.255.255.255", 1))  # não envia nada; só descobre a interface de rede
            return s.getsockname()[0]
    except OSError:
        return None


if __name__ == "__main__":
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", "8000"))
    app = create_app()
    print(f"Controle de Rotina rodando na porta {port}.")
    print(f"  Neste computador: http://127.0.0.1:{port}")
    if (ip := enderecos_locais()) and host == "0.0.0.0":
        print(f"  Na rede do escritório: http://{ip}:{port}")
    print("Deixe esta janela aberta. Para parar, pressione Ctrl+C.")
    serve(app, host=host, port=port, threads=8)
