"""XTeCu - Cursor-Agenten ueber Telegram bedienen.

Bewusst ausserhalb aller Projektverzeichnisse, damit derselbe Bot mehrere
Projekte bedienen kann und die Zugangsdaten in keinem Repository landen.
"""

__version__ = "1.0.0"

# Der Ersatz fuer den Windows-Fehler des SDK muss greifen, bevor irgendetwas
# den SDK benutzt. Ihn hier zu setzen nimmt die Reihenfolge aus dem Spiel -
# sonst haengt es daran, welches Modul zufaellig zuerst importiert. Ausserhalb
# von Windows tut der Aufruf nichts.
from . import windows_bruecke as _windows_bruecke  # noqa: E402

_windows_bruecke.anwenden()
