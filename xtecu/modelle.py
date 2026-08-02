"""Modelle auflisten und auswaehlen, ohne Namen auswendig zu koennen.

Die Liste kommt vom Cursor-Dienst selbst (``models.list``) - also auch die
Anzeigenamen und welche Parameter ein Modell ueberhaupt versteht. Hier steht
damit **keine** gepflegte Namensliste, die veralten koennte; nur die Reihenfolge
der Favoriten ist Geschmackssache und in ``FAVORITEN`` festgehalten.

Ein Modell wird als Kurzform geschrieben: ``claude-opus-5:high``. Vor dem
Doppelpunkt die Kennung, dahinter beliebig viele Zusaetze:

* ``low`` ``medium`` ``high`` ``xhigh`` ``max`` - wie gruendlich (``effort``)
* ``fast`` - die schnelle Bedienung, wenn das Modell sie anbietet
* ``1m`` - grosses Kontextfenster

Zusaetze, die ein Modell nicht kennt, fallen still weg. So laesst sich dieselbe
Kurzform auf jedes Modell anwenden, ohne dass ein Lauf daran scheitert.
"""

from __future__ import annotations

import json
import logging
import time
from dataclasses import dataclass, field

from cursor_sdk import CursorClient, ModelParameterValue, ModelSelection

from .einstellungen import ZUSTAND

logger = logging.getLogger("xtecu.modelle")

SPEICHER = ZUSTAND / "modelle.json"
#: Wie lange die Liste als frisch gilt. Modelle kommen selten dazu.
HALTBAR_SEK = 24 * 3600

#: Reihenfolge der Vorschlaege. Nur Kennung und Gruendlichkeit - die Namen
#: holt sich die Anzeige beim Dienst. Was es nicht gibt, faellt weg.
FAVORITEN: list[str] = [
    "claude-opus-5:high",
    "claude-opus-5:max",
    "claude-sonnet-5:high",
    "composer-2.5",
    "gpt-5.6-sol:high",
    "grok-4.5:high",
    "gemini-3.1-pro:high",
]

_EFFORT = ("low", "medium", "high", "xhigh", "max")


@dataclass
class Modell:
    """Was der Dienst ueber ein Modell weiss."""

    id: str
    name: str
    #: Parametername -> erlaubte Werte, etwa {"effort": {"low", ..., "max"}}
    parameter: dict[str, set[str]] = field(default_factory=dict)

    def kennt(self, name: str, wert: str) -> bool:
        return wert in self.parameter.get(name, set())


class Katalog:
    """Die Modelliste, zwischengespeichert."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._modelle: dict[str, Modell] = {}
        self._geholt = 0.0
        self._aus_speicher()

    # -- beschaffen ---------------------------------------------------- #

    def _aus_speicher(self) -> None:
        if not SPEICHER.exists():
            return
        try:
            roh = json.loads(SPEICHER.read_text("utf-8"))
            self._geholt = float(roh.get("stand", 0))
            self._modelle = {
                m["id"]: Modell(m["id"], m["name"],
                                {k: set(v) for k, v in m["parameter"].items()})
                for m in roh.get("modelle", [])}
        except Exception as exc:
            logger.warning("Gespeicherte Modelliste unlesbar (%s)", exc)

    def _in_speicher(self) -> None:
        SPEICHER.write_text(json.dumps({
            "stand": self._geholt,
            "modelle": [{"id": m.id, "name": m.name,
                         "parameter": {k: sorted(v)
                                       for k, v in m.parameter.items()}}
                        for m in self._modelle.values()],
        }, indent=1), "utf-8")

    def auffrischen(self) -> int:
        """Liste neu beim Dienst holen. Gibt die Anzahl zurueck."""
        klient = CursorClient.launch_bridge()
        try:
            roh = klient.models.list(api_key=self._api_key)
        finally:
            try:
                klient.close()
            except Exception:
                pass

        self._modelle = {}
        for m in roh:
            if m.id == "default":
                continue
            self._modelle[m.id] = Modell(
                id=m.id,
                name=m.display_name or m.id,
                parameter={p.id: {v.value for v in p.values}
                           for p in (m.parameters or ())},
            )
        self._geholt = time.time()
        self._in_speicher()
        return len(self._modelle)

    def sicherstellen(self) -> None:
        if self._modelle and time.time() - self._geholt < HALTBAR_SEK:
            return
        try:
            self.auffrischen()
        except Exception as exc:
            # Ohne Liste laeuft es trotzdem: Die Kurzform wird dann
            # unveraendert durchgereicht und der Dienst entscheidet.
            logger.warning("Modelliste nicht erreichbar (%s)", exc)

    # -- nachschlagen --------------------------------------------------- #

    def alle(self) -> list[Modell]:
        self.sicherstellen()
        return sorted(self._modelle.values(), key=lambda m: m.name.lower())

    def favoriten(self) -> list[str]:
        """Die Vorschlagsliste, um nicht Vorhandenes bereinigt."""
        self.sicherstellen()
        if not self._modelle:
            return list(FAVORITEN)
        return [k for k in FAVORITEN if kennung(k) in self._modelle]

    def name(self, kurz: str) -> str:
        """Lesbare Bezeichnung, etwa ``Opus 5 (gruendlich)``."""
        self.sicherstellen()
        kenn, zusaetze = _zerlegen(kurz)
        m = self._modelle.get(kenn)
        text = m.name if m else kenn
        stufe = next((z for z in zusaetze if z in _EFFORT), None)
        beiwerk = []
        if stufe:
            beiwerk.append({"low": "flüchtig", "medium": "normal",
                            "high": "gründlich", "xhigh": "sehr gründlich",
                            "max": "maximal"}[stufe])
        if "fast" in zusaetze:
            beiwerk.append("schnell")
        if "1m" in zusaetze:
            beiwerk.append("großer Kontext")
        return f"{text} ({', '.join(beiwerk)})" if beiwerk else text

    def auswahl(self, kurz: str) -> ModelSelection:
        """Kurzform in das umsetzen, was der SDK erwartet.

        Zusaetze, die das Modell nicht kennt, bleiben weg - lieber ein Lauf mit
        Standardeinstellung als ein abgelehnter Lauf.
        """
        self.sicherstellen()
        kenn, zusaetze = _zerlegen(kurz)
        m = self._modelle.get(kenn)
        werte: list[ModelParameterValue] = []

        def setzen(name: str, wert: str) -> None:
            if m is None or m.kennt(name, wert):
                werte.append(ModelParameterValue(id=name, value=wert))

        stufe = next((z for z in zusaetze if z in _EFFORT), None)
        if stufe:
            setzen("effort", stufe)
            # Ohne "thinking" bleibt die Gruendlichkeit bei manchen Modellen
            # wirkungslos - sie greift erst im denkenden Betrieb.
            setzen("thinking", "true")
        if "fast" in zusaetze:
            setzen("fast", "true")
        if "1m" in zusaetze:
            setzen("context", "1m")
        return ModelSelection(id=kenn, params=tuple(werte))

    def gibt_es(self, kennung_: str) -> bool:
        self.sicherstellen()
        return not self._modelle or kennung_ in self._modelle


def kennung(kurz: str) -> str:
    return _zerlegen(kurz)[0]


def _zerlegen(kurz: str) -> tuple[str, list[str]]:
    teile = [t.strip().lower() for t in kurz.strip().split(":") if t.strip()]
    if not teile:
        return "", []
    return teile[0], teile[1:]
