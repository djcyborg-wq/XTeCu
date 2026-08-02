"""Nur ein Dienst darf laufen.

Telegram laesst nur einen Abfrager je Bot zu. Ein zweiter Start bekommt
``409 Conflict``, und schlimmer: Laufen zwei Dienste abwechselnd durch, landen
Befehle mal beim einen, mal beim anderen - mit getrennten Agentensitzungen.
Am 02.08.2026 liefen so unbemerkt drei Instanzen, weil unter Windows das
Beenden des Startfensters den Python-Prozess nicht mitnimmt.

Die Sperre ist eine Datei mit der Prozessnummer. Liegt sie da und lebt der
Prozess noch, bricht der Start ab. Steht dort eine Leiche - etwa nach einem
Absturz - wird sie uebernommen.
"""

from __future__ import annotations

import atexit
import os
from pathlib import Path

from .einstellungen import ZUSTAND

DATEI = ZUSTAND / "dienst.pid"


def _lebt(pid: int) -> bool:
    if os.name == "nt":
        import subprocess
        try:
            aus = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=15).stdout
        except Exception:
            return True  # im Zweifel als lebend behandeln
        return str(pid) in aus
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def belegen() -> None:
    """Sperre setzen oder mit einer verstaendlichen Meldung abbrechen."""
    ZUSTAND.mkdir(exist_ok=True)
    if DATEI.exists():
        try:
            alt = int(DATEI.read_text("utf-8").strip())
        except ValueError:
            alt = 0
        if alt and alt != os.getpid() and _lebt(alt):
            raise SystemExit(
                f"XTeCu laeuft bereits (Prozess {alt}). Zwei Dienste am selben "
                f"Bot stehlen sich die Nachrichten.\n"
                f"Beenden mit:  Stop-Process -Id {alt} -Force")

    DATEI.write_text(str(os.getpid()), "utf-8")
    atexit.register(freigeben)


def freigeben() -> None:
    try:
        if DATEI.exists() and DATEI.read_text("utf-8").strip() == str(os.getpid()):
            DATEI.unlink()
    except OSError:
        pass
