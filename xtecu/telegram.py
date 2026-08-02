"""Telegram-Anbindung: warten, empfangen, senden.

Gewartet wird per *Longpolling*: Eine Abfrage bleibt bis zu 50 Sekunden offen
und kehrt zurueck, sobald eine Nachricht da ist. Das ist eine haengende
HTTP-Verbindung, kein Modell - **das Warten verbraucht nichts**. Kosten
entstehen erst, wenn ein Befehl tatsaechlich einen Agentenlauf ausloest.
"""

from __future__ import annotations

import html
import logging
import time
from dataclasses import dataclass

import httpx

logger = logging.getLogger("xtecu.telegram")

#: Telegram nimmt hoechstens 4096 Zeichen je Nachricht. Etwas Luft lassen,
#: weil die HTML-Auszeichnung beim Trennen mitzaehlt.
MAX_ZEICHEN = 3800


@dataclass
class Nachricht:
    update_id: int
    chat_id: int
    text: str
    absender: str


class Bot:
    def __init__(self, token: str, timeout: int = 50) -> None:
        self._basis = f"https://api.telegram.org/bot{token}"
        self._token = token
        self._timeout = timeout
        self._offset: int | None = None
        # Lesetimeout ueber der Longpoll-Dauer, sonst bricht httpx die
        # Verbindung ab, bevor Telegram antwortet.
        self._klient = httpx.Client(timeout=httpx.Timeout(timeout + 15))

    def close(self) -> None:
        self._klient.close()

    def _ohne_token(self, text: object) -> str:
        """httpx nennt bei Fehlern die volle URL - und die enthaelt den Token.

        Ohne das steht das Passwort des Bots im Protokoll, sobald Telegram
        einmal einen Fehler liefert (erlebt am 02.08.2026 bei einem 409).
        """
        return str(text).replace(self._token, "<token>")

    def _ruf(self, methode: str, **daten):
        antwort = self._klient.post(f"{self._basis}/{methode}", json=daten)
        antwort.raise_for_status()
        nutz = antwort.json()
        if not nutz.get("ok"):
            raise RuntimeError(
                f"Telegram lehnte {methode} ab: {self._ohne_token(nutz)}")
        return nutz.get("result")

    # -- empfangen ---------------------------------------------------- #

    def warte_auf_nachrichten(self) -> list[Nachricht]:
        """Blockiert bis zu ``timeout`` Sekunden. Bei Netzproblemen leer."""
        try:
            roh = self._ruf("getUpdates", timeout=self._timeout,
                            offset=self._offset,
                            allowed_updates=["message"])
        except Exception as exc:
            logger.warning("Abfrage fehlgeschlagen (%s) - neuer Versuch",
                           self._ohne_token(exc))
            time.sleep(5)
            return []

        out: list[Nachricht] = []
        for u in roh or []:
            self._offset = u["update_id"] + 1
            m = u.get("message") or {}
            text = (m.get("text") or "").strip()
            if not text:
                continue
            von = m.get("from") or {}
            out.append(Nachricht(
                update_id=u["update_id"],
                chat_id=m["chat"]["id"],
                text=text,
                absender=von.get("username") or von.get("first_name") or "?",
            ))
        return out

    def verwerfe_rueckstand(self) -> int:
        """Alles wegwerfen, was waehrend der Auszeit aufgelaufen ist.

        Sonst arbeitet der Dienst beim Start Befehle von gestern ab - bei einem
        Bot, der handeln darf, waere das die unangenehmste Art von Ueberraschung.
        """
        roh = self._ruf("getUpdates", timeout=0, offset=self._offset) or []
        if roh:
            self._offset = roh[-1]["update_id"] + 1
            self._ruf("getUpdates", timeout=0, offset=self._offset)
        return len(roh)

    # -- senden ------------------------------------------------------- #

    def sende(self, chat_id: int | str, text: str) -> None:
        for teil in _aufteilen(text):
            try:
                self._ruf("sendMessage", chat_id=chat_id, text=teil,
                          parse_mode="HTML", disable_web_page_preview=True)
            except Exception as exc:
                # Meist eine kaputte HTML-Auszeichnung im Modelltext. Lieber
                # roh zustellen als die Antwort verlieren.
                logger.warning("Senden mit HTML scheiterte (%s) - roh",
                               self._ohne_token(exc))
                self._ruf("sendMessage", chat_id=chat_id,
                          text=_entschaerfen(teil),
                          disable_web_page_preview=True)

    def zeige_tippt(self, chat_id: int | str) -> None:
        try:
            self._ruf("sendChatAction", chat_id=chat_id, action="typing")
        except Exception:
            pass


def _aufteilen(text: str) -> list[str]:
    """Lange Antworten an Zeilengrenzen teilen, nicht mitten im Wort."""
    text = text.strip() or "(leere Antwort)"
    if len(text) <= MAX_ZEICHEN:
        return [text]
    teile, aktuell = [], ""
    for zeile in text.splitlines(keepends=True):
        while len(zeile) > MAX_ZEICHEN:  # eine einzelne Zeile ist zu lang
            if aktuell:
                teile.append(aktuell)
                aktuell = ""
            teile.append(zeile[:MAX_ZEICHEN])
            zeile = zeile[MAX_ZEICHEN:]
        if len(aktuell) + len(zeile) > MAX_ZEICHEN:
            teile.append(aktuell)
            aktuell = ""
        aktuell += zeile
    if aktuell.strip():
        teile.append(aktuell)
    return teile


def _entschaerfen(text: str) -> str:
    return html.unescape(text)
