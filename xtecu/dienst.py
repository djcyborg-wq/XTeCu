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

from . import modelle, sperre
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
                "/modell": self._modell, "/modelle": self._modell,
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
            "  <code>/modell</code> - Modelle zeigen, <code>/modell 2</code> "
            "schaltet um\n"
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

    def _modell(self, n: Nachricht, rest: str) -> None:
        """Modell zeigen oder umschalten.

        Die Ziffern zeigen immer auf die Favoritenliste, nie auf die zuletzt
        angezeigte - sonst hinge die Bedeutung von <code>/modell 2</code> davon
        ab, was man vorher aufgerufen hat.
        """
        katalog = self._sitzungen.katalog
        sitzung = self._sitzungen.fuer(self._aktuell)
        favoriten = katalog.favoriten()
        wunsch = rest.strip().lower()

        if wunsch in ("alle", "all"):
            zeilen = [f"<code>{m.id}</code> — {m.name}" for m in katalog.alle()]
            self._bot.sende(n.chat_id,
                "<b>Alle Modelle</b>\n" + "\n".join(zeilen)
                + "\n\nUmschalten mit der Kennung, Gründlichkeit anhängen:\n"
                  "<code>/modell claude-sonnet-5:high</code>")
            return

        if wunsch in ("auffrischen", "aktualisieren"):
            try:
                self._bot.sende(n.chat_id,
                                f"{katalog.auffrischen()} Modelle geholt.")
            except Exception as exc:
                self._bot.sende(n.chat_id, "Die Liste war nicht zu erreichen: "
                                + html.escape(str(exc)[:200]))
            return

        if not wunsch:
            zeilen = []
            for i, kurz in enumerate(favoriten, 1):
                marke = " <b>(aktiv)</b>" if kurz == sitzung.modell else ""
                zeilen.append(f"<b>{i}</b>  {katalog.name(kurz)}{marke}")
            jetzt = katalog.name(sitzung.modell)
            fremd = "" if sitzung.modell in favoriten else \
                f"\n\nZurzeit eingestellt: <b>{jetzt}</b> " \
                f"(<code>{html.escape(sitzung.modell)}</code>)"
            self._bot.sende(n.chat_id,
                "<b>Modell</b>\n" + "\n".join(zeilen) + fremd
                + "\n\n<code>/modell 2</code> schaltet um.\n"
                  "<code>/modell alle</code> zeigt die vollständige Liste.")
            return

        if wunsch.isdigit():
            i = int(wunsch)
            if not 1 <= i <= len(favoriten):
                self._bot.sende(n.chat_id,
                                f"Es gibt die Nummern 1 bis {len(favoriten)}.")
                return
            neu = favoriten[i - 1]
        else:
            neu = wunsch
            if not katalog.gibt_es(modelle.kennung(neu)):
                self._bot.sende(n.chat_id,
                    f"<code>{html.escape(modelle.kennung(neu))}</code> kenne "
                    "ich nicht. <code>/modell alle</code> zeigt die Liste.")
                return

        sitzung.modell_setzen(neu)
        self._bot.sende(n.chat_id,
                        f"Jetzt <b>{katalog.name(neu)}</b>. Das Gespräch läuft "
                        "weiter, nur der Denker wechselt.")

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
            s = self._sitzungen.fuer(self._aktuell)
            self._bot.sende(n.chat_id,
                            f"Nichts zu tun.\nProjekt <b>{self._aktuell.name}</b>"
                            f"\nModell <b>{self._sitzungen.katalog.name(s.modell)}</b>")
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
        sitzung = self._sitzungen.fuer(self._aktuell)
        modell = sitzung.modell

        def arbeiten() -> None:
            begonnen = time.monotonic()
            try:
                with Lebenszeichen(self._bot, n.chat_id, sitzung,
                                   self._cfg.lauf_timeout) as puls:
                    antwort = sitzung.frage(text)
                if puls.abgewuergt:
                    return  # der Abbruch wurde schon gemeldet
            except Exception as exc:
                logger.exception("Agentenlauf gescheitert")
                antwort = (f"Der Agent kam nicht durch: "
                           f"{html.escape(type(exc).__name__)}: "
                           f"{html.escape(str(exc)[:400])}")
            finally:
                self._beschaeftigt_seit = None

            dauer = time.monotonic() - begonnen
            fuss = (f"\n\n<i>{self._aktuell.name} · "
                    f"{self._sitzungen.katalog.name(modell)} · "
                    f"{dauer:.0f}s · {datetime.now():%H:%M}</i>")
            self._bot.sende(n.chat_id, _fuer_telegram(antwort) + fuss)

        self._arbeiter = threading.Thread(target=arbeiten, daemon=True,
                                          name="xtecu-arbeiter")
        self._arbeiter.start()


class Lebenszeichen:
    """Zeigt, dass noch gearbeitet wird - und beendet, was zu lange braucht.

    Ein Agentenlauf kann Minuten dauern, etwa wenn er sich erst in Unterlagen
    einliest. Telegrams Tippanzeige verfaellt nach fuenf Sekunden; ohne
    Auffrischung sitzt man vor einem stummen Chat und weiss nicht, ob der
    Auftrag ueberhaupt angekommen ist (erlebt am 02.08.2026).

    Also: Tippanzeige alle vier Sekunden, nach einer Weile eine kurze
    Zwischenmeldung, und nach ``grenze`` Sekunden der Abbruch - sonst haenge
    ein stiller Lauf den Bot fuer alle weiteren Fragen zu.
    """

    #: Erst ab hier melden. Kurze Laeufe brauchen keine Zwischennachricht.
    ERSTE_MELDUNG = 75
    WEITERE_ALLE = 180

    def __init__(self, bot: Bot, chat_id: int, sitzung, grenze: int) -> None:
        self._bot = bot
        self._chat = chat_id
        self._sitzung = sitzung
        self._grenze = grenze
        self._fertig = threading.Event()
        self.abgewuergt = False
        self._faden = threading.Thread(target=self._laufen, daemon=True,
                                       name="xtecu-lebenszeichen")

    def __enter__(self) -> "Lebenszeichen":
        self._faden.start()
        return self

    def __exit__(self, *_) -> None:
        self._fertig.set()

    def _laufen(self) -> None:
        begonnen = time.monotonic()
        naechste_meldung = self.ERSTE_MELDUNG
        while not self._fertig.wait(4):
            self._bot.zeige_tippt(self._chat)
            offen = time.monotonic() - begonnen

            if offen >= self._grenze:
                self.abgewuergt = True
                logger.warning("Lauf nach %.0fs abgebrochen - Zeitgrenze", offen)
                self._sitzung.abbrechen()
                lang = (f"{self._grenze // 60} Minuten" if self._grenze >= 60
                        else f"{self._grenze} Sekunden")
                self._bot.sende(self._chat, f"Nach {lang} abgebrochen - da lief "
                                            "etwas aus dem Ruder.")
                return

            if offen >= naechste_meldung:
                naechste_meldung += self.WEITERE_ALLE
                self._bot.sende(self._chat,
                                f"Bin noch dran ({int(offen)}s). /stop bricht ab.")


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
