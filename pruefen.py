"""Selbsttest: Stimmen Zugaenge, Pfade und der Weg zum Agenten?

    .\\.venv\\Scripts\\python.exe pruefen.py

Der letzte Schritt startet einen echten (kleinen) Agentenlauf und kostet
entsprechend wenig. Mit ``--schnell`` bleibt er aus.
"""

from __future__ import annotations

import sys
from pathlib import Path

import httpx

from xtecu.einstellungen import laden

FEHLER = 0


def sagen(gut: bool, text: str) -> None:
    global FEHLER
    if not gut:
        FEHLER += 1
    print(f"  [{'ok ' if gut else 'FEHLT'}] {text}")


print("== Einstellungen ==")
cfg = laden()
sagen(True, f"{len(cfg.projekte)} Projekt(e), Standard: {cfg.standard}")
for s, p in cfg.projekte.items():
    sagen(p.existiert(), f"{s}: {p.pfad}")
    for u in p.unterlagen:
        sagen((Path(p.pfad) / u).exists(), f"    Unterlage {u}")

print("\n== Telegram ==")
antwort = httpx.get(f"https://api.telegram.org/bot{cfg.bot_token}/getMe",
                    timeout=30).json()
sagen(antwort.get("ok", False),
      f"Bot @{(antwort.get('result') or {}).get('username', '?')}")
sagen(bool(cfg.chat_id),
      f"Chat-ID {cfg.chat_id or '(leer - Dienst starten und dem Bot schreiben)'}")

if "--schnell" not in sys.argv:
    print("\n== Cursor ==")
    from cursor_sdk import Agent, AgentOptions, LocalAgentOptions

    from xtecu.modelle import Katalog

    projekt = cfg.projekt(None)
    # Ueber den Katalog, genau wie der Dienst. Die Kurzform "id:high" darf
    # nicht roh an den SDK gehen - er kennt nur die nackte Kennung und lehnt
    # sie sonst ab. Ein Selbsttest, der anders vorgeht als der Dienst, meldet
    # Fehler, die es nicht gibt.
    katalog = Katalog(cfg.cursor_key)
    try:
        sagen(True, f"Modell {katalog.name(projekt.modell)}")
        e = Agent.prompt(
            "Antworte nur mit dem Wort: bereit",
            AgentOptions(api_key=cfg.cursor_key,
                         model=katalog.auswahl(projekt.modell),
                         local=LocalAgentOptions(cwd=projekt.pfad)))
        sagen(e.status == "finished",
              f"Agentenlauf {e.status}: {(e.result or '').strip()[:60]}")
    except Exception as exc:
        sagen(False, f"{type(exc).__name__}: {str(exc)[:200]}")

print()
print("Alles in Ordnung." if not FEHLER else f"{FEHLER} Punkt(e) offen.")
sys.exit(1 if FEHLER else 0)
