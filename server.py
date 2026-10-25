"""Kanban-Board: kleiner lokaler Server auf http://localhost:8814.

Liefert index.html aus und speichert das Board in board.json (gleicher Ordner).
Nur Python-Standardbibliothek, lauscht nur auf 127.0.0.1.
"""
import json
import os
import tempfile
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8814
ORDNER = Path(__file__).resolve().parent
DATEI = ORDNER / "board.json"
SEITE = ORDNER / "index.html"
MAX_GROESSE = 5 * 1024 * 1024  # 5 MB reichen für Tausende Aufgaben
ERLAUBTE_HOSTS = {f"localhost:{PORT}", f"127.0.0.1:{PORT}"}
SPERRE = threading.Lock()  # immer nur ein Speichervorgang gleichzeitig

LEER = {
    "wipLimit": 3,
    "spalten": [
        {"id": "offen", "name": "Offen"},
        {"id": "arbeit", "name": "In Arbeit"},
        {"id": "erledigt", "name": "Erledigt"},
    ],
    "aufgaben": [],
}


def board_laden():
    if not DATEI.exists():
        return LEER
    return json.loads(DATEI.read_text(encoding="utf-8"))


def board_speichern(daten):
    # Erst in eine eigene Zwischendatei schreiben, dann tauschen: so geht bei einem Absturz nichts kaputt.
    with SPERRE:
        fd, tmp = tempfile.mkstemp(dir=ORDNER, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(daten, f, ensure_ascii=False, indent=2)
            os.replace(tmp, DATEI)
        except OSError:
            Path(tmp).unlink(missing_ok=True)
            raise


def board_gueltig(daten):
    return (
        isinstance(daten, dict)
        and isinstance(daten.get("aufgaben"), list)
        and isinstance(daten.get("spalten"), list)
        and isinstance(daten.get("wipLimit"), int)
    )


class Handler(BaseHTTPRequestHandler):
    def _antwort(self, code, inhalt, typ="application/json; charset=utf-8"):
        body = inhalt if isinstance(inhalt, bytes) else inhalt.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _host_ok(self):
        # Schutz vor DNS-Rebinding: fremde Seiten, die sich als localhost ausgeben, abweisen.
        if self.headers.get("Host") in ERLAUBTE_HOSTS:
            return True
        self._antwort(403, '{"fehler": "falscher Host"}')
        return False

    def do_GET(self):
        if not self._host_ok():
            return
        if self.path in ("/", "/index.html"):
            self._antwort(200, SEITE.read_bytes(), "text/html; charset=utf-8")
        elif self.path == "/api/board":
            try:
                self._antwort(200, json.dumps(board_laden(), ensure_ascii=False))
            except ValueError:
                self._antwort(500, '{"fehler": "board.json ist beschädigt"}')
        else:
            self._antwort(404, '{"fehler": "nicht gefunden"}')

    def do_PUT(self):
        if not self._host_ok():
            return
        origin = self.headers.get("Origin")
        if origin and origin.split("://", 1)[-1] not in ERLAUBTE_HOSTS:
            return self._antwort(403, '{"fehler": "fremde Seite"}')
        if self.path != "/api/board":
            return self._antwort(404, '{"fehler": "nicht gefunden"}')
        # Nur JSON annehmen: fremde Seiten können ohne Rückfrage des Browsers kein JSON senden.
        if self.headers.get("Content-Type", "").split(";")[0] != "application/json":
            return self._antwort(415, '{"fehler": "nur JSON"}')
        try:
            laenge = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            laenge = 0
        if laenge <= 0 or laenge > MAX_GROESSE:
            return self._antwort(413, '{"fehler": "zu gross oder leer"}')
        try:
            daten = json.loads(self.rfile.read(laenge))
        except ValueError:
            return self._antwort(400, '{"fehler": "kein gültiges JSON"}')
        if not board_gueltig(daten):
            return self._antwort(400, '{"fehler": "Board-Format falsch"}')
        try:
            board_speichern(daten)
        except OSError:
            return self._antwort(500, '{"fehler": "board.json konnte nicht geschrieben werden"}')
        self._antwort(200, '{"ok": true}')

    def log_message(self, *args):
        pass  # keine Zeile pro Klick im Terminal


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"Kanban-Board läuft: {url}  (beenden mit Ctrl+C)")
    if not os.environ.get("KEIN_BROWSER"):
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
