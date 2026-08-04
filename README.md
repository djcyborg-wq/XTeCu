# XTeCu

Cursor-Agenten über Telegram bedienen. Der Bot [@XTeCu_bot](https://t.me/XTeCu_bot)
nimmt eine Nachricht entgegen, lässt einen Agenten im Projektverzeichnis
arbeiten und schickt die Antwort zurück.

Das Verzeichnis liegt bewusst **außerhalb** aller Projekte: Ein Bot bedient
mehrere Projekte, und die Zugangsdaten geraten so in kein Repository und auf
keinen Server.

Getestet unter Windows 10 mit Python 3.12. Mindestens Python 3.11 ist nötig
(`tomllib`).

## Einrichten

1. **Bot anlegen.** In Telegram an [@BotFather](https://t.me/BotFather):
   `/newbot`. Er gibt einen Token aus.
2. **Cursor-Schlüssel holen.** [cursor.com/dashboard](https://cursor.com/dashboard)
   → Integrations → API Keys.
3. **`.env` anlegen.** `.env.example` kopieren und beide Werte eintragen,
   `XTECU_CHAT_ID` erst einmal leer lassen.
4. **`projekte.toml` anpassen** — mindestens Pfad und Einweisung des eigenen
   Projekts.
5. **Starten** (`.\start.ps1`), dem Bot in Telegram irgendetwas schreiben. Er
   antwortet mit der Chat-ID. Die in die `.env` eintragen, neu starten.

Der Umweg über den ersten Start ist Absicht: Bis die ID eingetragen ist, führt
der Bot nichts aus, sondern nennt nur, wer da geschrieben hat.

## Starten und beenden

```powershell
cd C:\Users\dj_cyborg\XTeCu
.\start.ps1
```

Das Fenster muss offen bleiben. Der Dienst läuft auf diesem Rechner, weil die
Agenten hier in den Projektverzeichnissen arbeiten — auf dem Telefon läuft nur
Telegram.

Beenden mit `.\stop.ps1`. Das Schließen des Fensters genügt unter Windows
**nicht**: Der Python-Prozess läuft weiter und fängt weiter Nachrichten ab.
Gegen versehentliche Zweitstarts gibt es eine Sperre — ein zweiter Dienst würde
sich mit dem ersten die Nachrichten teilen, mit getrennten Agentensitzungen.

Selbsttest, wenn etwas klemmt (prüft Pfade, Bot und einen echten Agentenlauf;
mit `--schnell` ohne den Lauf):

```powershell
.\.venv\Scripts\python.exe pruefen.py
```

## Bedienen

Jede normale Nachricht ist ein Auftrag an den Agenten im aktiven Projekt.

| Befehl | Wirkung |
| --- | --- |
| `/modell` | Modelle anzeigen, `/modell 2` schaltet um |
| `/projekt` | Projekte anzeigen |
| `/projekt xflops` | umschalten |
| `/neu` | Gespräch von vorn beginnen |
| `/stop` | laufenden Auftrag abbrechen |
| `/status` | was gerade läuft |
| `/hilfe` | Übersicht |

Es läuft immer nur **ein** Auftrag. Schreibt man währenddessen etwas, sagt der
Bot, woran er noch arbeitet und wie lange schon — die Nachricht wird nicht
heimlich in eine Warteschlange gelegt. Der Dienst bleibt dabei ansprechbar:
`/stop` und `/status` kommen auch mitten in einem langen Lauf durch.

Ein Lauf kann Minuten dauern. Damit man nicht vor einem stummen Chat sitzt,
bleibt die Tippanzeige durchgehend stehen, nach 75 Sekunden kommt eine kurze
Zwischenmeldung und danach alle drei Minuten eine weitere.

Nach 45 Minuten bricht der Bot ab (`XTECU_LAUF_GRENZE_MIN` in der `.env`).
Diese Grenze ist bewusst großzügig: Sie soll nur den Fall abfangen, dass ein
Lauf gar nicht mehr zurückkommt und damit alle weiteren Fragen blockiert —
gegen einen bloß langen Lauf gibt es die Zwischenmeldungen und `/stop`. Ein
Abbruch ist teuer, denn hat der Agent unterwegs schon Dateien geändert, bleiben
sie halbfertig liegen; der Bot weist beim Abbruch darauf hin.

Am Fuß jeder Antwort stehen Projekt, Modell und die Dauer des Laufs.

## Das Modell wechseln

`/modell` zeigt eine kurze Vorschlagsliste mit Nummern; `/modell 2` schaltet
um. Die Nummern zeigen **immer** auf diese Liste, nie auf die zuletzt
angezeigte — sonst hinge die Bedeutung von `/modell 2` davon ab, was man vorher
aufgerufen hat. `/modell alle` zeigt alle rund 33 Modelle zum Kopieren,
`/modell auffrischen` holt die Liste neu (sie wird sonst einen Tag lang
behalten).

Die Liste kommt vom Cursor-Dienst selbst, samt Anzeigenamen und der Frage,
welche Parameter ein Modell überhaupt versteht. Hier ist also keine
Namensliste gepflegt, die veralten könnte — nur die Reihenfolge der Vorschläge
steht in `FAVORITEN` in `xtecu/modelle.py`.

Geschrieben wird ein Modell als Kurzform: `claude-opus-5:high`. Hinter dem
Doppelpunkt steht, wie gründlich gedacht werden soll (`low` bis `max`),
dazu wahlweise `fast` und `1m` für das große Kontextfenster. Zusätze, die ein
Modell nicht kennt, fallen still weg — `composer-2.5:max` läuft also einfach
ohne Denkstufe, statt den Auftrag scheitern zu lassen.

Umschalten geht **mitten im Gespräch**: Der Agent bleibt derselbe, nur der
Denker wechselt. Getestet — nach dem Wechsel wusste das neue Modell noch, was
im Gespräch davor stand. Die Wahl gilt je Projekt und überlebt einen Neustart;
der Ausgangswert steht in `projekte.toml`.

## Wenn etwas schiefgeht

Störungen des Cursor-Dienstes gehen meist von selbst vorbei. Das Absenden eines
Auftrags wird deshalb bis zu zweimal wiederholt (nach 8 und 20 Sekunden) —
allerdings nur das **Absenden**, denn solange kein Lauf entstanden ist, kann
auch keiner doppelt starten. Bleibt die Störung, bekommt man einen Satz, der
sagt, woran es liegt, statt eines Fehlerprotokolls.

Im Protokoll des Dienstes steht zu jedem Lauf Start, Status, Dauer und
Antwortlänge; eine gestörte Telegram-Abfrage wird gezählt und die Erholung
ausdrücklich vermerkt. Eine einzelne Warnung ohne Folgemeldung wäre sonst nicht
von einem Dauerausfall zu unterscheiden.

## Was das Warten kostet

Nichts. Gewartet wird per Longpolling: eine HTTP-Verbindung, die bis zu 50
Sekunden offen bleibt und zurückkehrt, sobald etwas ankommt. Kein Modell ist
dabei beteiligt. Verbraucht wird erst, wenn ein Auftrag tatsächlich einen
Agentenlauf startet.

## Was der Agent weiß — und was nicht

Ein Agent, der hier startet, kennt **nicht** den Verlauf eines Chats aus der
Cursor-Oberfläche. Der SDK führt einen eigenen Agentenspeicher; die IDs der
Oberflächen-Chats sind ihm unbekannt (geprüft am 02.08.2026:
`agents.list(runtime="local", cwd=...)` liefert für ein Verzeichnis mit
laufenden Chats null Einträge).

Gedächtnis entsteht deshalb auf zwei Wegen:

1. **Innerhalb einer Sitzung** hält der SDK den Faden. Die Agenten-ID liegt
   unter `zustand/`, sodass Folgefragen auch einen Neustart des Dienstes
   überleben. `/neu` setzt zurück.
2. **Über Sitzungen hinweg** trägt die Einweisung aus `projekte.toml`: ein
   kurzer Projektstand plus die Unterlagen, in denen Entscheidungen samt
   Begründung stehen. Das ist ohnehin, wie das Gedächtnis dieser Projekte
   funktioniert — auch ein langer Chat in der Oberfläche wird irgendwann
   verdichtet. Wer will, dass der Bot etwas weiß, schreibt es in die Dokumente.

## Wenn zwei Agenten am selben Verzeichnis arbeiten

Sobald neben dem Bot auch jemand in der Cursor-Oberfläche an einem Projekt
arbeitet, sehen beide dieselben Dateien, aber nicht das Gespräch des anderen.
Änderungen bemerken sie also, die Begründung dahinter nicht.

In XFlops ist das so gelöst: `docs/99_arbeitsjournal.md` nimmt beide Seiten auf
— was getan wurde, warum, und ob es lokal liegt, committet ist oder auf dem
Server läuft. Die Einweisung des Bots und die Regel
`.cursor/rules/arbeitsjournal.mdc` im Projekt verlangen beides: vor dem
Anfangen nachlesen und melden, was der andere getan hat, nach dem Ändern
eintragen.

Das löst das Nacherzählen, nicht das Gleichzeitig-Arbeiten. Fassen beide zur
selben Zeit dieselbe Datei an, hilft kein Protokoll — am sichersten bleibt,
nacheinander zu arbeiten.

## Neues Projekt anschließen

Ein Eintrag in `projekte.toml`, sonst nichts:

```toml
[projekt.beispiel]
name = "Mein Projekt"
pfad = "C:/Users/dj_cyborg/Beispiel"
modell = "claude-opus-5:high"
einweisung = "Worum es geht, in wenigen Sätzen."
unterlagen = ["README.md"]
```

`unterlagen` sind die Dateien, die der Agent zu Beginn einer Sitzung liest —
das Gedächtnis des Projekts. `einweisung` und `unterlagen` dürfen fehlen, dann
fängt der Agent bei null an.

Dort gehören **nur kurze Dateien** hinein. In XFlops stand anfangs auch das
Umstellungsdokument mit 170.000 Zeichen darin; die erste Frage einer Sitzung
brauchte damit über sechs Minuten, weil der Agent sich erst durch alles las.
Lange Dokumente nennt man besser in der `einweisung` als Nachschlagewerk, mit
dem ausdrücklichen Hinweis, sie nicht auf Verdacht zu lesen.

## Sicherheit

* Nur die Chat-ID aus `XTECU_CHAT_ID` darf Befehle geben, alles andere wird
  abgewiesen und protokolliert. Das ist die einzige Schranke, die zählt: Wer in
  diesen Chat kommt, hat einen Agenten mit vollen Schreibrechten in den
  Projektverzeichnissen. **Telefon mit Sperre versehen.**
* Der Cursor-Schlüssel hat Vollzugriff auf das Cursor-Konto. Er steht in `.env`
  und nirgends sonst. Aus Protokollmeldungen wird der Bot-Token entfernt —
  `httpx` nennt bei Fehlern die volle URL, und die enthält ihn.
* Der Agent arbeitet ohne Rückfrage. Er kann Dateien ändern, Befehle ausführen
  und — im XFlops-Projekt — auf den Server ausrollen. Wer das enger will,
  schreibt es in die `einweisung` des Projekts.
* Beim Start wirft der Dienst alles weg, was während seiner Auszeit aufgelaufen
  ist. Sonst arbeitete er Befehle von gestern ab.

## Aufbau

| Datei | Zweck |
| --- | --- |
| `xtecu/dienst.py` | Hauptschleife, Befehle |
| `xtecu/telegram.py` | Longpolling, Senden, Nachrichten teilen |
| `xtecu/agent.py` | Cursor-SDK, Sitzung je Projekt |
| `xtecu/modelle.py` | Modellliste vom Dienst, Kurzform auflösen |
| `xtecu/einstellungen.py` | `.env` und `projekte.toml` lesen |
| `xtecu/windows_bruecke.py` | Ersatz für einen SDK-Fehler unter Windows |
| `xtecu/sperre.py` | verhindert einen zweiten Dienst am selben Bot |
| `projekte.toml` | Projektregister |
| `pruefen.py` | Selbsttest |
| `start.ps1` / `stop.ps1` | Dienst starten und beenden |
| `zustand/` | Agenten-ID und Modellwahl je Projekt, Modellliste, Sperre |

Der Hauptfaden wartet auf Nachrichten und bleibt dabei immer ansprechbar; die
eigentliche Arbeit läuft in einem zweiten Faden. Nur so kann während eines
langen Agentenlaufs noch ein `/stop` ankommen.

Nichts in `zustand/` ist unersetzlich — wird der Ordner gelöscht, beginnen die
Gespräche von vorn und die Modellliste wird neu geholt.

### Der Windows-Ersatz

Der Cursor-SDK startet unter Windows seinen Brückenprozess nicht: Er liest
dessen Startmeldung, indem er die `stderr`-Pipe auf nicht-blockierend setzt und
bei `selectors` anmeldet — beides arbeitet unter Windows nur mit Sockets. Der
Aufruf endet mit `OSError: [WinError 10038]`, bevor irgendein Agent läuft.
`windows_bruecke.py` ersetzt die Funktion durch eine Fassung, die dasselbe
leistet, aber `stderr` in einem Hintergrundfaden blockierend liest. Das
Zeilenformat kommt weiter aus dem SDK, damit wir bei einer Formatänderung nicht
auseinanderlaufen. Fällt der Ersatz eines Tages weg, weil der SDK das selbst
behebt, meldet sich `anwenden()` einfach nicht mehr zuständig.

Der Ersatz wird in `xtecu/__init__.py` gesetzt, also beim ersten Import des
Pakets. Das nimmt die Reihenfolge aus dem Spiel: Sonst hinge es daran, welches
Modul zufällig zuerst den SDK importiert — ein Fehler, in den `pruefen.py`
prompt gelaufen ist.
