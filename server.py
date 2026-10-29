"""Kanban-Board: kleiner lokaler Server auf http://localhost:8814.

Liefert index.html aus und speichert das Board in der Datenbank kanban.db (SQLite, gleicher Ordner).
Eine alte board.json wird beim ersten Start einmal übernommen und bleibt als Sicherung liegen.
Nur Python-Standardbibliothek, lauscht nur auf 127.0.0.1.
"""
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

PORT = 8814
ORDNER = Path(__file__).resolve().parent
DB = ORDNER / "kanban.db"
ALT = ORDNER / "board.json"  # früherer Speicherort, wird nur noch gelesen
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


@contextmanager
def verbinden():
    # Speichert bei Erfolg, nimmt bei Fehler alles zurück und schliesst die Verbindung immer.
    db = sqlite3.connect(DB)
    try:
        db.execute("PRAGMA journal_mode=WAL")  # übersteht Abstürze, Lesen blockiert Schreiben nicht
        with db:
            yield db
    finally:
        db.close()


def db_einrichten():
    with verbinden() as db:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS einstellungen (schluessel TEXT PRIMARY KEY, wert TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS spalten (
                id TEXT PRIMARY KEY, name TEXT NOT NULL, position INTEGER NOT NULL, extra TEXT NOT NULL DEFAULT '{}');
            CREATE TABLE IF NOT EXISTS aufgaben (
                id TEXT PRIMARY KEY, titel TEXT NOT NULL, notiz TEXT NOT NULL, spalte TEXT NOT NULL,
                position INTEGER NOT NULL, extra TEXT NOT NULL DEFAULT '{}');
            """
        )
        befuellt = db.execute("SELECT 1 FROM einstellungen WHERE schluessel = 'wipLimit'").fetchone()
    # Am Inhalt entscheiden, nicht an der Datei: bricht der Import ab, wird er beim nächsten Start wiederholt.
    if not befuellt:
        start = json.loads(ALT.read_text(encoding="utf-8")) if ALT.exists() else LEER
        if not board_gueltig(start):
            raise SystemExit("board.json hat ein falsches Format – nichts übernommen, bitte prüfen.")
        board_speichern(start)


def board_laden():
    with SPERRE, verbinden() as db:  # nie mitten in ein Speichern hinein lesen
        wip = db.execute("SELECT wert FROM einstellungen WHERE schluessel = 'wipLimit'").fetchone()
        spalten = [
            {**json.loads(extra), "id": id, "name": name}
            for id, name, extra in db.execute("SELECT id, name, extra FROM spalten ORDER BY position")
        ]
        aufgaben = [
            {**json.loads(extra), "id": id, "titel": titel, "notiz": notiz, "spalte": spalte}
            for id, titel, notiz, spalte, extra in db.execute(
                "SELECT id, titel, notiz, spalte, extra FROM aufgaben ORDER BY position")
        ]
    if wip is None:
        raise ValueError("Datenbank ist leer")  # nie ein leeres Board ausliefern, das dann gespeichert würde
    return {"wipLimit": int(wip[0]), "spalten": spalten, "aufgaben": aufgaben}


def _extra(eintrag, bekannt):
    # Felder, für die es (noch) keine eigene Spalte gibt, gehen nicht verloren, sondern landen hier.
    return json.dumps({k: v for k, v in eintrag.items() if k not in bekannt}, ensure_ascii=False)


def board_speichern(daten):
    # Alles in einem Rutsch: entweder steht der neue Stand komplett in der Datenbank oder gar nicht.
    with SPERRE, verbinden() as db:
        db.execute("DELETE FROM spalten")
        db.execute("DELETE FROM aufgaben")
        db.execute("INSERT OR REPLACE INTO einstellungen VALUES ('wipLimit', ?)", (str(daten["wipLimit"]),))
        db.executemany(
            "INSERT INTO spalten VALUES (?, ?, ?, ?)",
            [(str(s["id"]), str(s.get("name", "")), i, _extra(s, {"id", "name"}))
             for i, s in enumerate(daten["spalten"])],
        )
        db.executemany(
            "INSERT INTO aufgaben VALUES (?, ?, ?, ?, ?, ?)",
            [(str(a["id"]), str(a.get("titel", "")), str(a.get("notiz", "")), str(a.get("spalte", "")), i,
              _extra(a, {"id", "titel", "notiz", "spalte"}))
             for i, a in enumerate(daten["aufgaben"])],
        )


def board_gueltig(daten):
    return (
        isinstance(daten, dict)
        and isinstance(daten.get("aufgaben"), list)
        and isinstance(daten.get("spalten"), list)
        and isinstance(daten.get("wipLimit"), int)
        and not isinstance(daten["wipLimit"], bool)
        and all(isinstance(x, dict) and "id" in x for x in daten["spalten"] + daten["aufgaben"])
    )


class Handler(BaseHTTPRequestHandler):
    def _antwort(self, code, inhalt, typ="application/json; charset=utf-8"):
        body = inhalt if isinstance(inhalt, bytes) else inhalt.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", typ)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Kanban-Speicher", "sqlite")  # daran erkennt Kanban.app, dass kein alter Server läuft
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
            except (ValueError, sqlite3.Error):
                self._antwort(500, '{"fehler": "Datenbank kanban.db ist nicht lesbar"}')
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
        except (OSError, sqlite3.Error):
            return self._antwort(500, '{"fehler": "Datenbank kanban.db konnte nicht geschrieben werden"}')
        self._antwort(200, '{"ok": true}')

    def log_message(self, *args):
        pass  # keine Zeile pro Klick im Terminal


if __name__ == "__main__":
    db_einrichten()
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    url = f"http://localhost:{PORT}"
    print(f"Kanban-Board läuft: {url}  (beenden mit Ctrl+C)")
    if not os.environ.get("KEIN_BROWSER"):
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
