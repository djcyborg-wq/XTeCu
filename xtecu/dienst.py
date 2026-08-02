"""Der Dienst: wartet auf Telegram, laesst Agenten arbeiten, meldet zurueck.

Aufbau in einem Satz: Der Hauptfaden wartet auf Nachrichten und bleibt dabei
immer ansprechbar, die eigentliche Arbeit laeuft in einem zweiten Faden. Nur
so kann waehrend eines langen Agentenlaufs noch ein ``/stop`` ankommen.
"""

from __future__ import annotations

import html
import logging
import re
import threading
import time
from datetime import datetime

from . import sperre
from .agent import Sitzungen
from .einstellungen import Konfiguration, Projekt, laden
from .telegram import Bot, Nachricht

logger = logging.getLogger("xtecu")


class Dienst:
    def __init__(self, cfg: Konfiguration) -> None:
        self._cfg = cfg
        self._bot = Bot(cfg.bot_token, cfg.abfrage_timeout)
        self._sitzungen = Sitzungen(cfg)
        self._aktuell: Projekt = cfg.projekt(None)
        self._arbeiter: threading.Thread | None = None
        self._beschaeftigt_seit: float | None = None
        self._letzte_frage = ""

    # -- Hauptschleife -------------------------------------------------- #

    def laufen(self) -> None:
        weg = self._bot.verwerfe_rueckstand()
        if weg:
            logger.info("%d alte Nachricht(en) verworfen", weg)

        logger.info("Bereit. Projekt: %s (%s)",
                    self._aktuell.name, self._aktuell.pfad)
        if self._cfg.chat_id:
            self._bot.sende(self._cfg.chat_id,
                            f"XTeCu ist da. Projekt <b>{self._aktuell.name}</b>. "
                            f"/hilfe zeigt die Befehle.")
        else:
            logger.warning("XTECU_CHAT_ID ist leer - die erste Nachricht "
                           "nennt die ID, dann in die .env eintragen.")

        while True:
            for n in self._bot.warte_auf_nachrichten():
                try:
                    self._behandeln(n)
                except Exception:
                    logger.exception("Nachricht fehlgeschlagen")
                    self._bot.sende(n.chat_id, "Da ist etwas schiefgegangen. "
                                               "Das Protokoll weiss mehr.")

    # -- Zugang --------------------------------------------------------- #

    def _darf(self, n: Nachricht) -> bool:
        if not self._cfg.chat_id:
            # Einrichtungslage: ID melden, aber noch nichts ausfuehren.
            logger.warning("Nachricht von Chat %s (%s) - noch nicht "
                           "freigeschaltet", n.chat_id, n.absender)
            self._bot.sende(
                n.chat_id,
                "Noch nicht freigeschaltet.\n\nTrage in der Datei "
                f"<code>.env</code> ein:\n<code>XTECU_CHAT_ID={n.chat_id}"
                "</code>\n\nDanach den Dienst neu starten.")
            return False
        if str(n.chat_id) != str(self._cfg.chat_id):
            logger.warning("Fremder Chat %s (%s) abgewiesen - Text: %.80s",
                           n.chat_id, n.absender, n.text)
            return False
        return True

    # -- Befehle -------------------------------------------------------- #

    def _behandeln(self, n: Nachricht) -> None:
        if not self._darf(n):
            return

        text = n.text.strip()
        if text.startswith("/"):
            befehl, _, rest = text.partition(" ")
            befehl = befehl.split("@")[0].lower()
            behandler = {
                "/start": self._hilfe, "/hilfe": self._hilfe,
                "/help": self._hilfe,
                "/projekt": self._projekt, "/projekte": self._projekt,
                "/neu": self._neu,
                "/stop": self._stop,
                "/status": self._status,
            }.get(befehl)
            if behandler:
                behandler(n, rest.strip())
                return
            self._bot.sende(n.chat_id,
                            f"Den Befehl {html.escape(befehl)} kenne ich nicht. "
                            "/hilfe zeigt, was geht.")
            return

        self._beauftragen(n, text)

    def _hilfe(self, n: Nachricht, rest: str) -> None:
        liste = "\n".join(
            f"  <code>{s}</code> - {p.name}"
            + ("  (aktiv)" if s == self._aktuell.schluessel else "")
            for s, p in self._cfg.projekte.items())
        self._bot.sende(n.chat_id,
            "<b>XTeCu</b> - Cursor per Telegram.\n\n"
            "Schreib einfach los, jede normale Nachricht geht als Auftrag an "
            "den Agenten im aktiven Projekt.\n\n"
            "<b>Befehle</b>\n"
            "  <code>/projekt</code> - Projekte zeigen\n"
            "  <code>/projekt xflops</code> - umschalten\n"
            "  <code>/neu</code> - Gespraech von vorn beginnen\n"
            "  <code>/stop</code> - laufenden Auftrag abbrechen\n"
            "  <code>/status</code> - was gerade laeuft\n\n"
            f"<b>Projekte</b>\n{liste}\n\n"
            "Das Warten auf Nachrichten kostet nichts - erst ein Auftrag "
            "startet einen Agenten.")

    def _projekt(self, n: Nachricht, rest: str) -> None:
        if not rest:
            zeilen = []
            for s, p in self._cfg.projekte.items():
                marke = " <b>(aktiv)</b>" if s == self._aktuell.schluessel else ""
                fehlt = "" if p.existiert() else "  [Pfad fehlt!]"
                zeilen.append(f"<code>{s}</code> - {p.name}{marke}{fehlt}\n"
                              f"    <code>{html.escape(p.pfad)}</code>")
            self._bot.sende(n.chat_id, "\n".join(zeilen)
                            + "\n\nUmschalten: <code>/projekt name</code>")
            return

        wahl = rest.split()[0].lower()
        if wahl not in self._cfg.projekte:
            self._bot.sende(n.chat_id, f"Kein Projekt <code>{html.escape(wahl)}"
                                       "</code>. /projekt zeigt die Liste.")
            return
        if self._beschaeftigt_seit is not None:
            self._bot.sende(n.chat_id, "Es laeuft noch ein Auftrag. Erst /stop.")
            return

        self._aktuell = self._cfg.projekte[wahl]
        hinweis = "" if self._aktuell.existiert() else \
            f"\n\nAchtung: {html.escape(self._aktuell.pfad)} gibt es nicht."
        self._bot.sende(n.chat_id,
                        f"Jetzt am Projekt <b>{self._aktuell.name}</b>."
                        + hinweis)

    def _neu(self, n: Nachricht, rest: str) -> None:
        if self._beschaeftigt_seit is not None:
            self._bot.sende(n.chat_id, "Es laeuft noch ein Auftrag. Erst /stop.")
            return
        self._sitzungen.fuer(self._aktuell).neu_beginnen()
        self._bot.sende(n.chat_id,
                        f"Gespraech zu <b>{self._aktuell.name}</b> zurueckgesetzt. "
                        "Der naechste Auftrag beginnt mit der Einweisung von vorn.")

    def _stop(self, n: Nachricht, rest: str) -> None:
        if self._beschaeftigt_seit is None:
            self._bot.sende(n.chat_id, "Es laeuft gerade nichts.")
            return
        if self._sitzungen.fuer(self._aktuell).abbrechen():
            self._bot.sende(n.chat_id, "Abbruch angefordert.")
        else:
            self._bot.sende(n.chat_id,
                            "Liess sich nicht abbrechen. Der Lauf endet von "
                            "selbst, die Antwort kommt dann noch.")

    def _status(self, n: Nachricht, rest: str) -> None:
        if self._beschaeftigt_seit is None:
            self._bot.sende(n.chat_id,
                            f"Nichts zu tun. Projekt <b>{self._aktuell.name}</b>, "
                            f"Modell <code>{self._aktuell.modell}</code>.")
            return
        dauer = int(time.monotonic() - self._beschaeftigt_seit)
        self._bot.sende(n.chat_id,
                        f"Laeuft seit {dauer}s an: "
                        f"<i>{html.escape(self._letzte_frage[:200])}</i>\n\n"
                        "/stop bricht ab.")

    # -- Auftrag -------------------------------------------------------- #

    def _beauftragen(self, n: Nachricht, text: str) -> None:
        if self._beschaeftigt_seit is not None:
            dauer = int(time.monotonic() - self._beschaeftigt_seit)
            self._bot.sende(n.chat_id,
                            f"Ich arbeite noch ({dauer}s) an: "
                            f"<i>{html.escape(self._letzte_frage[:120])}</i>\n\n"
                            "Warte kurz oder /stop.")
            return
        if not self._aktuell.existiert():
            self._bot.sende(n.chat_id,
                            f"Das Verzeichnis {html.escape(self._aktuell.pfad)} "
                            "gibt es nicht.")
            return

        self._letzte_frage = text
        self._beschaeftigt_seit = time.monotonic()
        self._bot.zeige_tippt(n.chat_id)

        def arbeiten() -> None:
            begonnen = time.monotonic()
            try:
                antwort = self._sitzungen.fuer(self._aktuell).frage(text)
            except Exception as exc:
                logger.exception("Agentenlauf gescheitert")
                antwort = (f"Der Agent kam nicht durch: "
                           f"{html.escape(type(exc).__name__)}: "
                           f"{html.escape(str(exc)[:400])}")
            finally:
                self._beschaeftigt_seit = None

            dauer = time.monotonic() - begonnen
            fuss = (f"\n\n<i>{self._aktuell.name} - {dauer:.0f}s - "
                    f"{datetime.now():%H:%M}</i>")
            self._bot.sende(n.chat_id, _fuer_telegram(antwort) + fuss)

        self._arbeiter = threading.Thread(target=arbeiten, daemon=True,
                                          name="xtecu-arbeiter")
        self._arbeiter.start()


def _fuer_telegram(text: str) -> str:
    """Markdown des Modells in das schmale HTML von Telegram uebersetzen.

    Telegram kennt nur eine Handvoll Auszeichnungen und wirft die ganze
    Nachricht zurueck, wenn ein ``<`` unerwartet auftaucht. Deshalb erst alles
    entschaerfen, dann nur das Noetigste wieder als Auszeichnung setzen.
    """
    text = html.escape(text)
    text = re.sub(r"```[a-zA-Z]*\n(.*?)```", r"<pre>\1</pre>", text,
                  flags=re.DOTALL)
    text = re.sub(r"`([^`\n]+)`", r"<code>\1</code>", text)
    text = re.sub(r"\*\*([^*\n]+)\*\*", r"<b>\1</b>", text)
    # Ueberschriften traegt Telegram nicht - fett tut es auch.
    text = re.sub(r"^#{1,6}\s*(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)
    return text


def haupt() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s  %(message)s",
        datefmt="%H:%M:%S")
    logging.getLogger("httpx").setLevel(logging.WARNING)
    sperre.belegen()
    try:
        Dienst(laden()).laufen()
    except KeyboardInterrupt:
        print("\nBeendet.")
    finally:
        sperre.freigeben()
