"""Der Cursor-SDK startet unter Windows seinen Bruecken-Prozess nicht.

``cursor_sdk._bridge._read_discovery`` liest die Startmeldung der Bruecke, indem
es deren ``stderr``-Pipe auf nicht-blockierend setzt (``os.set_blocking``) und
bei ``selectors`` anmeldet. Unter Windows arbeiten beide nur mit **Sockets**,
nicht mit Pipes - der Aufruf endet mit ``OSError: [WinError 10038] Ein Vorgang
bezog sich auf ein Objekt, das kein Socket ist``, noch bevor irgendein Agent
laeuft. Geprueft am 02.08.2026 mit cursor-sdk auf Python 3.12.10.

Hier wird die Funktion durch eine Fassung ersetzt, die dasselbe leistet, aber
ohne Socket-Annahmen: Ein Hintergrund-Thread liest ``stderr`` Zeile fuer Zeile
blockierend, die Hauptschleife wartet mit Zeitgrenze auf die Startmeldung. Das
Zeilenformat kommt weiter aus ``parse_discovery_line`` des SDK, damit wir bei
einer Formataenderung nicht auseinanderlaufen.

``anwenden()`` muss **vor** dem ersten SDK-Aufruf laufen und ist mehrfach
aufrufbar. Auf anderen Betriebssystemen tut es nichts.
"""

from __future__ import annotations

import os
import queue
import threading
import time
from typing import Any, Mapping

_ANGEWENDET = False


def anwenden() -> bool:
    """Ersetzt das Einlesen der Startmeldung. Gibt zurueck, ob gepatcht wurde."""
    global _ANGEWENDET
    if _ANGEWENDET or os.name != "nt":
        return False

    import cursor_sdk._bridge as bruecke
    from cursor_sdk import CursorSDKError

    def lies_startmeldung(prozess, timeout: float) -> Mapping[str, Any]:
        if prozess.stderr is None:
            raise CursorSDKError("Die Bruecke hat keine Fehlerausgabe.")

        zeilen: "queue.Queue[str | None]" = queue.Queue()

        def leser() -> None:
            try:
                for zeile in prozess.stderr:
                    zeilen.put(zeile)
            finally:
                zeilen.put(None)

        threading.Thread(target=leser, daemon=True,
                         name="xtecu-bruecke-stderr").start()

        gesammelt: list[str] = []
        ende = time.monotonic() + timeout
        while time.monotonic() < ende:
            try:
                zeile = zeilen.get(timeout=0.2)
            except queue.Empty:
                if prozess.poll() is not None:
                    raise CursorSDKError(
                        "Die Bruecke endete vor der Startmeldung: "
                        + "".join(gesammelt))
                continue
            if zeile is None:
                raise CursorSDKError(
                    "Die Bruecke sendete keine Startmeldung: "
                    + "".join(gesammelt))
            gesammelt.append(zeile)
            gefunden = bruecke.parse_discovery_line(zeile)
            if gefunden is not None:
                return gefunden
        raise CursorSDKError(
            f"Die Bruecke meldete sich nicht innerhalb von {timeout:g} Sekunden.")

    bruecke._read_discovery = lies_startmeldung
    _ANGEWENDET = True
    return True
