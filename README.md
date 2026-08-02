# XTeCu

Cursor-Agenten über Telegram bedienen. Der Bot [@XTeCu_bot](https://t.me/XTeCu_bot)
nimmt eine Nachricht entgegen, lässt einen Agenten im Projektverzeichnis
arbeiten und schickt die Antwort zurück.

Das Verzeichnis liegt bewusst **außerhalb** aller Projekte: Ein Bot bedient
mehrere Projekte, und die Zugangsdaten geraten so in kein Repository und auf
keinen Server.

## Starten

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

Selbsttest vor dem Start:

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

## Das Modell wechseln

`/modell` zeigt eine kurze Vorschlagsliste mit Nummern; `/modell 2` schaltet
um. Die Nummern zeigen **immer** auf diese Liste, nie auf die zuletzt
angezeigte — sonst hinge die Bedeutung von `/modell 2` davon ab, was man vorher
aufgerufen hat. `/modell alle` zeigt alle rund 33 Modelle zum Kopieren.

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

## Neues Projekt anschließen

Fünf Zeilen in `projekte.toml`, sonst nichts:

```toml
[projekt.beispiel]
name = "Mein Projekt"
pfad = "C:/Users/dj_cyborg/Beispiel"
modell = "composer-2.5"
einweisung = "Worum es geht, in wenigen Sätzen."
unterlagen = ["README.md"]
```

## Sicherheit

* Nur die Chat-ID aus `XTECU_CHAT_ID` darf Befehle geben, alles andere wird
  abgewiesen und protokolliert. Das ist die einzige Schranke, die zählt: Wer in
  diesen Chat kommt, hat einen Agenten mit vollen Schreibrechten in den
  Projektverzeichnissen. **Telefon mit Sperre versehen.**
* Der Cursor-Schlüssel hat Vollzugriff auf das Cursor-Konto. Er steht in `.env`
  und nirgends sonst.
* Der Agent arbeitet ohne Rückfrage. Er kann Dateien ändern, Befehle ausführen
  und — im XFlops-Projekt — auf den Server ausrollen. Wer das enger will,
  schreibt es in die `einweisung` des Projekts.

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
| `zustand/` | gemerkte Agenten-IDs |

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
