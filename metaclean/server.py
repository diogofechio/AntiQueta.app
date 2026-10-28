"""Servidor local: serve a interface e processa as imagens só na memória."""

import base64
import json
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from . import core
from .exiftool import ExiftoolMissing

STATIC = Path(__file__).parent / "static"


class Handler(BaseHTTPRequestHandler):
    server_version = "AntiQueta.IA"

    def log_message(self, fmt, *args):  # sem logs com nomes de arquivos
        pass

    def _send(self, status, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Security-Policy",
                         "default-src 'self'; img-src 'self' blob: data:; "
                         "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            return self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
        self._send(404, {"error": "não encontrado"})

    def do_POST(self):
        host = (self.headers.get("Host") or "").rsplit(":", 1)[0]
        if host not in ("127.0.0.1", "localhost"):  # bloqueia DNS rebinding
            return self._send(403, {"error": "host não permitido"})
        if self.headers.get("Origin") not in (None, f"http://{self.headers.get('Host')}"):
            return self._send(403, {"error": "origem não permitida"})
        size = int(self.headers.get("Content-Length") or 0)
        if size <= 0:
            return self._send(400, {"error": "arquivo vazio"})
        if size > core.MAX_BYTES:
            return self._send(413, {"error": "arquivo maior que 100 MB"})
        data = self.rfile.read(size)
        name = unquote(self.headers.get("X-Filename") or "imagem")
        try:
            if self.path == "/api/inspect":
                return self._send(200, core.inspect(data))
            if self.path == "/api/clean":
                keep = self.headers.get("X-Keep-Orientation", "1") == "1"
                before = core.inspect(data)
                keep_icc = self.headers.get("X-Keep-ICC", "1") == "1"
                cleaned = core.clean(data, keep_orientation=keep, keep_icc=keep_icc)
                after = core.inspect(cleaned)
                return self._send(200, {
                    "filename": core.cleaned_name(name, before["format"]),
                    "size_before": len(data),
                    "size_after": len(cleaned),
                    "removed": before["summary"]["removable"],
                    "after": after,
                    "data": base64.b64encode(cleaned).decode(),
                })
            self._send(404, {"error": "não encontrado"})
        except (core.FormatError, ExiftoolMissing) as exc:
            self._send(422, {"error": str(exc)})
        except Exception as exc:  # noqa: BLE001 - mostra o erro na interface
            self._send(500, {"error": f"Falha ao processar: {exc}"})


class Server(ThreadingHTTPServer):
    # No Windows, SO_REUSEADDR deixa dois processos ouvirem a mesma porta.
    allow_reuse_address = False


def _bind(host, port):
    """Usa a porta pedida; se estiver ocupada, tenta as seguintes e por fim uma livre qualquer."""
    for p in [*range(port, port + 10), 0]:
        try:
            return Server((host, p), Handler)
        except OSError:
            continue
    raise OSError("nenhuma porta livre")


def serve(host="127.0.0.1", port=8765, open_browser=True):
    httpd = _bind(host, port)
    url = f"http://{host}:{httpd.server_address[1]}/"
    print(f"AntiQueta.IA rodando em {url}")
    print("Para encerrar, feche esta janela (ou Ctrl+C).")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
