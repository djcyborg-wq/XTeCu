"""Cursor-Agenten starten und den Faden halten.

Zum Gedaechtnis, weil das der haeufigste Irrtum ist: Ein Agent, der hier
startet, kennt **nicht** den Verlauf eines Gespraechs aus der
Cursor-Oberflaeche. Geprueft am 02.08.2026 - der SDK fuehrt einen eigenen
Agentenspeicher, ``agents.list(runtime="local", cwd=...)`` liefert fuer ein
Verzeichnis mit laufenden Oberflaechen-Chats null Eintraege, und die ID eines
solchen Chats beantwortet der SDK mit ``AgentNotFoundError``.

Kontinuitaet entsteht deshalb auf zwei Wegen:

1. **Innerhalb einer Sitzung** haelt der SDK den Faden. Die Agenten-ID wird
   auf Platte gemerkt, sodass sie auch einen Neustart des Dienstes uebersteht;
   Folgefragen wie "und jetzt verkauf den" funktionieren damit.
2. **Ueber Sitzungen hinweg** traegt die Einweisung: ein kurzer Projektstand
   plus die Unterlagen, in denen die Entscheidungen samt Begruendung stehen.
   Das ist ohnehin, wie das Gedaechtnis dieser Projekte funktioniert - der
   Verlauf eines langen Chats wird auch in der Oberflaeche verdichtet.
"""

from __future__ import annotations

import json
import logging
import threading
import time

from . import windows_bruecke
from .einstellungen import ZUSTAND, Konfiguration, Projekt
from .modelle import Katalog

windows_bruecke.anwenden()

from cursor_sdk import Agent, AgentOptions, LocalAgentOptions  # noqa: E402
from cursor_sdk.errors import (InternalServerError,  # noqa: E402
                               NetworkError, RateLimitError)

logger = logging.getLogger("xtecu.agent")

#: Stoerungen, die nichts mit dem Auftrag zu tun haben und meist von selbst
#: vergehen. Am 04.08.2026 lieferte der Cursor-Dienst dreimal binnen zwei
#: Minuten "internal error", danach lief alles wieder.
VORUEBERGEHEND = (InternalServerError, NetworkError, RateLimitError)

#: Wartezeiten vor dem naechsten Versuch. Wiederholt wird nur das Absenden -
#: dabei ist noch kein Lauf entstanden, den man doppelt starten koennte.
WARTEN = (8, 20)


class Sitzung:
    """Ein fortlaufendes Gespraech zu einem Projekt."""

    def __init__(self, cfg: Konfiguration, projekt: Projekt,
                 katalog: Katalog) -> None:
        self._cfg = cfg
        self._projekt = projekt
        self._katalog = katalog
        self._merker = ZUSTAND / f"{projekt.schluessel}.json"
        self._agent_id: str | None = None
        self._modell: str | None = None
        self._laden()
        self._laufend = None
        self._sperre = threading.Lock()

    # -- Gedaechtnis auf Platte --------------------------------------- #

    def _laden(self) -> None:
        if not self._merker.exists():
            return
        try:
            roh = json.loads(self._merker.read_text("utf-8"))
        except Exception:
            return
        self._agent_id = roh.get("agent_id")
        self._modell = roh.get("modell")

    def _sichern(self) -> None:
        self._merker.write_text(json.dumps(
            {"agent_id": self._agent_id, "modell": self._modell}), "utf-8")

    def _merke(self, agent_id: str | None) -> None:
        self._agent_id = agent_id
        self._sichern()

    def neu_beginnen(self) -> None:
        self._merke(None)

    # -- Modellwahl ---------------------------------------------------- #

    @property
    def modell(self) -> str:
        """Die gewaehlte Kurzform, sonst die aus ``projekte.toml``."""
        return self._modell or self._projekt.modell

    def modell_setzen(self, kurz: str) -> None:
        """Umschalten, ohne den Gespraechsfaden zu verlieren.

        Der Agent bleibt derselbe; das Modell steckt in den Optionen, die beim
        Fortsetzen erneut mitgehen. Man kann also mitten im Gespraech von einem
        schnellen auf ein gruendliches Modell wechseln.
        """
        self._modell = kurz
        self._sichern()

    @property
    def laeuft_schon(self) -> bool:
        return self._laufend is not None

    # -- Einweisung ---------------------------------------------------- #

    def _einweisung(self) -> str:
        """Was der Agent zu Beginn einer Sitzung wissen muss."""
        p = self._projekt
        teile = [
            f"Du arbeitest am Projekt {p.name} in {p.pfad}.",
            "Du wirst ueber Telegram angesprochen. Antworte deshalb kurz und "
            "in ganzen Saetzen, ohne Ueberschriften und ohne Tabellen - das "
            "liest jemand auf einem Telefon. Antworte auf Deutsch.",
        ]
        if p.einweisung:
            teile.append(p.einweisung)
        if p.unterlagen:
            liste = ", ".join(p.unterlagen)
            teile.append(
                "Du kennst den bisherigen Gespraechsverlauf nicht. Was "
                f"entschieden wurde und warum, steht in: {liste}. Lies dort "
                "nach, bevor du etwas ueber den Projektstand behauptest.")
        return "\n\n".join(teile)

    # -- Lauf ---------------------------------------------------------- #

    def _absenden(self, agent, auftrag: str):
        """Auftrag absenden, voruebergehende Stoerungen aussitzen.

        Wiederholt wird ausschliesslich das Absenden. Scheitert es, ist noch
        kein Lauf entstanden - es kann also keiner doppelt starten. Sobald der
        Lauf steht, wird nichts mehr wiederholt.
        """
        for versuch, pause in enumerate((*WARTEN, None), start=1):
            try:
                return agent.send(auftrag)
            except VORUEBERGEHEND as exc:
                if pause is None:
                    raise
                logger.warning(
                    "Absenden gescheitert (%s: %s) - Versuch %d von %d, "
                    "warte %ds", type(exc).__name__, str(exc)[:120],
                    versuch, len(WARTEN) + 1, pause)
                time.sleep(pause)

    def frage(self, text: str) -> str:
        """Eine Frage stellen und die Antwort abwarten."""
        with self._sperre:
            erste = self._agent_id is None
            auftrag = f"{self._einweisung()}\n\n---\n\n{text}" if erste else text

            optionen = AgentOptions(
                api_key=self._cfg.cursor_key,
                model=self._katalog.auswahl(self.modell),
                local=LocalAgentOptions(cwd=self._projekt.pfad),
            )

            if self._agent_id:
                try:
                    agent = Agent.resume(self._agent_id, optionen)
                except Exception as exc:
                    logger.warning(
                        "Fortsetzen von %s scheiterte (%s) - neue Sitzung",
                        self._agent_id, exc)
                    self._merke(None)
                    agent = Agent.create(optionen)
                    auftrag = f"{self._einweisung()}\n\n---\n\n{text}"
            else:
                agent = Agent.create(optionen)

            try:
                lauf = self._absenden(agent, auftrag)
                self._laufend = lauf
                kennung = getattr(lauf, "id", "?")
                logger.info("Lauf %s gestartet (Agent %s, Modell %s)",
                            kennung, agent.agent_id, self.modell)
                begonnen = time.monotonic()
                ergebnis = lauf.wait()
                # Ohne diese Zeile stehen im Protokoll nur Starts. Dann laesst
                # sich hinterher nicht sagen, ob ein Lauf lange brauchte oder
                # gar nicht zurueckkam - genau die Frage, die am 02.08.2026
                # eine Viertelstunde Suchen kostete.
                logger.info("Lauf %s %s nach %.0fs (%d Zeichen)", kennung,
                            ergebnis.status, time.monotonic() - begonnen,
                            len(ergebnis.result or ""))
                self._merke(agent.agent_id)

                if ergebnis.status == "error":
                    return ("Der Lauf ist unterwegs gescheitert. "
                            f"Kennung {getattr(lauf, 'id', '?')}.")
                if ergebnis.status == "cancelled":
                    return "Abgebrochen."
                return (ergebnis.result or "").strip() or "(keine Antwort)"
            finally:
                self._laufend = None
                try:
                    agent.close()
                except Exception:
                    pass

    def abbrechen(self) -> bool:
        lauf = self._laufend
        if lauf is None:
            return False
        try:
            if lauf.supports("cancel"):
                lauf.cancel()
                return True
        except Exception as exc:
            logger.warning("Abbrechen scheiterte: %s", exc)
        return False


class Sitzungen:
    """Je Projekt eine Sitzung, bei Bedarf angelegt."""

    def __init__(self, cfg: Konfiguration) -> None:
        self._cfg = cfg
        self.katalog = Katalog(cfg.cursor_key)
        self._nach_projekt: dict[str, Sitzung] = {}

    def fuer(self, projekt: Projekt) -> Sitzung:
        if projekt.schluessel not in self._nach_projekt:
            self._nach_projekt[projekt.schluessel] = Sitzung(
                self._cfg, projekt, self.katalog)
        return self._nach_projekt[projekt.schluessel]
