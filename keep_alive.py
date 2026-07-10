"""Mini servidor HTTP para que un servicio de uptime (UptimeRobot, Render, etc.)
le haga ping al bot y lo mantenga despierto.

No usa Flask a propósito, para no agregar una dependencia extra: alcanza con
el módulo estándar http.server. Se ejecuta en un hilo aparte para no bloquear
el bot de Discord.
"""

import logging
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

logger = logging.getLogger("bot.keep_alive")

PAGE = b"""<!DOCTYPE html>
<html lang="es">
<head>
  <meta charset="utf-8">
  <title>Bot status</title>
  <style>
    body { font-family: sans-serif; background:#0f1220; color:#e6e6f0; display:flex;
           align-items:center; justify-content:center; height:100vh; margin:0; }
    .card { text-align:center; }
    h1 { color:#57f287; }
  </style>
</head>
<body>
  <div class="card">
    <h1>&#9989; El bot esta activo</h1>
    <p>Este endpoint existe solo para que un servicio de uptime le haga ping.</p>
  </div>
</body>
</html>
"""


class PingHandler(BaseHTTPRequestHandler):
    timeout = 10

    def do_GET(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(PAGE)))
        self.end_headers()
        self.wfile.write(PAGE)

    def log_message(self, format, *args):
        # Silencia el log de cada request para no ensuciar la consola del bot.
        pass


def _run():
    raw_port = os.environ.get("PORT", "8080")
    try:
        port = int(raw_port)
    except ValueError:
        logger.error("PORT inválido (%r), usando 8080 por defecto.", raw_port)
        port = 8080

    try:
        server = HTTPServer(("0.0.0.0", port), PingHandler)
    except OSError:
        logger.exception("No se pudo iniciar el servidor de keep_alive en el puerto %d.", port)
        return

    logger.info("keep_alive escuchando en el puerto %d.", port)
    server.serve_forever()


def keep_alive():
    """Levanta el servidor de ping en un hilo en segundo plano."""
    thread = threading.Thread(target=_run, daemon=True)
    thread.start()
