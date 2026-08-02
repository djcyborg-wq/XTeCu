"""Zugangsdaten und Projektregister laden.

Die Zugangsdaten stehen in ``.env`` neben diesem Paket - bewusst ausserhalb
jedes Projektverzeichnisses, damit sie weder in ein Repository geraten noch
beim Ausrollen auf einen Server mitkopiert werden. Das XFlops-Projekt etwa
schiebt seine eigene ``.env`` bei jedem Deploy per ``scp`` auf den Server;
ein Cursor-Schluessel mit Kontovollzugriff hat dort nichts zu suchen.
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

WURZEL = Path(__file__).resolve().parent.parent
ENV_DATEI = WURZEL / ".env"
PROJEKT_DATEI = WURZEL / "projekte.toml"
ZUSTAND = WURZEL / "zustand"


def _env_laden() -> None:
    """``.env`` in die Prozessumgebung legen. Bereits gesetzte Werte gewinnen,
    damit sich einzelne Angaben beim Start ueberschreiben lassen."""
    if not ENV_DATEI.exists():
        raise SystemExit(
            f"Es fehlt {ENV_DATEI}. Vorlage: .env.example danebenlegen und "
            f"ausfuellen.")
    for zeile in ENV_DATEI.read_text(encoding="utf-8").splitlines():
        zeile = zeile.strip()
        if not zeile or zeile.startswith("#") or "=" not in zeile:
            continue
        name, wert = zeile.split("=", 1)
        os.environ.setdefault(name.strip(), wert.strip())


@dataclass
class Projekt:
    """Ein Arbeitsverzeichnis, das der Bot bedienen kann."""

    schluessel: str
    name: str
    pfad: str
    modell: str = "composer-2.5"
    einweisung: str = ""
    #: Dateien, die der Agent zu Beginn einer Sitzung lesen soll. Sie sind das
    #: Gedaechtnis des Projekts - der Agent kennt den Chatverlauf nicht, wohl
    #: aber, was aufgeschrieben wurde.
    unterlagen: list[str] = field(default_factory=list)

    def existiert(self) -> bool:
        return Path(self.pfad).is_dir()


@dataclass
class Konfiguration:
    cursor_key: str
    bot_token: str
    chat_id: str
    projekte: dict[str, Projekt]
    standard: str
    #: Sekunden, die eine Telegram-Abfrage offenhaelt. Reine Netzwerkwartezeit,
    #: kein Modell - das Warten kostet nichts.
    abfrage_timeout: int = 50
    #: Obergrenze fuer einen einzelnen Agentenlauf.
    lauf_timeout: int = 900

    def projekt(self, schluessel: str | None) -> Projekt:
        return self.projekte[schluessel or self.standard]


def laden() -> Konfiguration:
    _env_laden()

    fehlend = [n for n in ("CURSOR_API_KEY", "XTECU_BOT_TOKEN")
               if not os.environ.get(n)]
    if fehlend:
        raise SystemExit(f"In der .env fehlen: {', '.join(fehlend)}")

    if not PROJEKT_DATEI.exists():
        raise SystemExit(f"Es fehlt {PROJEKT_DATEI}.")
    roh = tomllib.loads(PROJEKT_DATEI.read_text(encoding="utf-8"))

    projekte: dict[str, Projekt] = {}
    for schluessel, eintrag in (roh.get("projekt") or {}).items():
        projekte[schluessel] = Projekt(
            schluessel=schluessel,
            name=eintrag.get("name", schluessel),
            pfad=eintrag["pfad"],
            modell=eintrag.get("modell", "composer-2.5"),
            einweisung=eintrag.get("einweisung", "").strip(),
            unterlagen=list(eintrag.get("unterlagen", [])),
        )
    if not projekte:
        raise SystemExit("In projekte.toml steht kein Projekt.")

    standard = roh.get("standard") or next(iter(projekte))
    if standard not in projekte:
        raise SystemExit(f"Standardprojekt '{standard}' ist nicht angelegt.")

    ZUSTAND.mkdir(exist_ok=True)
    return Konfiguration(
        cursor_key=os.environ["CURSOR_API_KEY"],
        bot_token=os.environ["XTECU_BOT_TOKEN"],
        chat_id=os.environ.get("XTECU_CHAT_ID", "").strip(),
        projekte=projekte,
        standard=standard,
    )
