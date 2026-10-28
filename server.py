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
    server_version = "LimpaMetadados"

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
                cleaned = core.clean(data, keep_orientation=keep)
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


def serve(host="127.0.0.1", port=8765, open_browser=True):
    httpd = ThreadingHTTPServer((host, port), Handler)
    url = f"http://{host}:{port}/"
    print(f"Limpa Metadados rodando em {url}  (Ctrl+C para sair)")
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
