# Conversational BI mit SLayer

Ein kleiner Python-Dienst für Auswertungen freigegebener Daten des Kantons Solothurn: genau drei MCP-Werkzeuge, native SLayer-Berechnung und ein transienter Query-Unterprozess. Das Repository enthält Code, normative Spezifikation, eingefrorene Quelldateien und unabhängige Sollwerte.

**Leitprinzip:** Der Agent darf alle fachlich möglichen Kombinationen innerhalb des freigegebenen Funktionsumfangs selbständig verwenden, ohne dass jede Benutzerfrage vorab bekannt sein muss.

Die Anwendung besteht aus einem Python-Dienst mit drei MCP-Werkzeugen. Sie übersetzt einen kleinen strukturierten Analysevertrag in native SLayer-Abfragen. SLayer übernimmt die Berechnung. Die Anwendung prüft die bekannten fachlichen und betrieblichen Grenzen. Ein separat entwickelter SQL-Planer, ein Java-Dienst und eine weitere Infrastrukturplattform gehören nicht zur ersten Version.

## Komplettpaket mit OpenWebUI

Voraussetzungen: Docker mit Compose und Python **ab 3.9** für das kleine Einrichtungsskript. Eine lokale Python-Projektinstallation und ein vorbereitetes Datenbundle sind nicht erforderlich. Der erste Imagebau sowie der Infomaniak-Chat benötigen Internet.

```sh
./start.sh
```

Danach [OpenWebUI öffnen](http://localhost:3003) und mit den übernommenen Admin-Zugangsdaten aus der lokalen `.env` anmelden. Das voreingestellte Modell **Agentic BI – SLayer** nutzt `Qwen/Qwen3.8-27B-FP8`, natives Function Calling und unsere drei MCP-Werkzeuge. Der MCP-Endpunkt ist [http://127.0.0.1:8003/mcp](http://127.0.0.1:8003/mcp).

Beim ersten Start übernimmt das Skript Provider-URL, Infomaniak-Token, Admin-Zugang und Signaturschlüssel aus `../dateninfrastruktur-agentic-bi-demo-001/.env`. Die eigene `.env` erhält Dateirechte `0600` und ist von Git und Docker-Buildkontext ausgeschlossen. Demo 001 bleibt unverändert. Ohne diese Nachbar-Konfiguration zuerst `.env.example` nach `.env` kopieren und die leeren Zugangswerte ergänzen. Hostports lassen sich mit `OPEN_WEBUI_HOST_PORT` und `AGENTIC_BI_HOST_PORT` in `.env` ändern.

OpenWebUI ist auf [v0.12.3](https://github.com/open-webui/open-webui/releases/tag/v0.12.3) mit unveränderlichem Image-Digest gepinnt, dem am 23.10.2026 geprüften neuesten stabilen Release. Anmeldung ist aktiv; Registrierung, Ollama und automatische Folgefragen sind deaktiviert. Das CSS stammt aus Demo 001. Die Modellkarte enthält den Analysevertrag und Beispiele. Maximal acht native Werkzeugrunden pro Antwort begrenzen fehlerhafte Wiederholungen des Modells.

Der Imagebau erzeugt das geprüfte Bundle direkt aus den eingefrorenen Originalen und nativen Modellen. Der MCP-Container verwendet ein schreibgeschütztes Root-Dateisystem, UID 10001, einen 256-MiB-Arbeitsbereich, eine CPU und 1 GiB RAM. Die Readiness-Probe steuert die Startreihenfolge. Beide veröffentlichten Ports sind an Loopback gebunden.

Erneutes `./start.sh` aktualisiert die verwaltete MCP-Verbindung und Modellkarte idempotent. Chats und Dateien bleiben im eigenen Volume `dateninfrastruktur-agentic-bi-demo-002_open-webui-data` erhalten. Stoppen mit `docker compose down`; `down -v` würde den WebUI-Datenbestand löschen. Für parallele WebUI-Instanzen unterschiedliche Browserprofile oder Hostnamen verwenden: Cookies unterscheiden keine Ports; ein altes Token einer anderen Instanz kann sonst die Anmeldung stören.

```sh
python3 scripts/openwebui.py check       # Provider, Modell und MCP wirklich prüfen
python3 scripts/openwebui.py seed        # Einrichtung erneut anwenden
python3 scripts/openwebui.py live-check  # zwei echte, kostenpflichtige Provider-Chats
# Einzelnen Live-Fall ausführen:
python3 scripts/openwebui.py live-check --case N02
uv run pytest -q                        # lokale Fach-, Betriebs- und Containerabnahme
```

`live-check` prüft F04 (649.6804637625776 samt unbekanntem Fahrzeugstichtag) und die fachliche Ablehnung N02. Es liest die zugehörigen tatsächlichen Werkzeugantworten und die gespeicherte Chatantwort. Mit `--reuse-chat F04=UUID` beziehungsweise `--reuse-chat N02=UUID` lassen sich vorhandene Abnahmechats ohne erneuten Provider-Aufruf prüfen. Diese Live-Prüfung läuft wegen der externen Modellnutzung bewusst separat von `pytest` und vom normalen Start. Einrichtungs- und Prüfberichte stehen ohne Zugangsdaten unter `build/openwebui-*.json`; Dockerfehler liefern einen Exitcode ungleich null. [OpenWebUI-Abnahme und Grenzen](OPENWEBUI_ABNAHME.md).

## Python-Dienst ohne WebUI starten und prüfen

Voraussetzungen: `uv`, Python 3.12.14 (durch `uv` installierbar), für die Containerabnahme Docker. Installation und Imagebau benötigen Netzwerk; Dienst und Abnahmetests anschliessend nicht.

```sh
uv sync --frozen
uv run python -m slayer_app.author build --manifest tests/fixtures/real/manifest.json --models models --output build/pilot-v1
uv run python -m slayer_app.author verify --bundle build/pilot-v1
SLAYER_APP_BUNDLE_DIR=build/pilot-v1 SLAYER_APP_WORK_DIR=build/work uv run python -m slayer_app.server
```

Ein bestehendes Bundle wird niemals überschrieben. Für einen Neubau einen neuen Ausgabepfad wählen. Standardadresse: `http://127.0.0.1:8000/mcp`, Probes: `/healthz` und `/readyz`. Eine Analyse belegt den einzigen Slot; weitere Analysen erhalten sofort `E_BUSY`. Suche und Beschreibung bleiben verfügbar. Die Analysefrist umfasst Prozessstart, Importe, Planung und Berechnung.

```sh
uv run pytest
docker build -t slayer-bi:local .
docker run --rm --read-only --user 12345:0 --cap-drop ALL --security-opt no-new-privileges \
  --cpus 1 --memory 1g --tmpfs /work:rw,size=268435456,mode=1777 \
  --mount type=bind,src="$PWD/build/pilot-v1",dst=/bundle,readonly \
  -p 127.0.0.1:8000:8000 slayer-bi:local
```

Das Bundle muss für die zugewiesene UID lesbar sein. `/work` ist die einzige benötigte beschreibbare Ablage; kein beschreibbares Home ist erforderlich. Der Dienst benötigt keinen ausgehenden Netzwerkzugriff. Eine Replik und ein Uvicorn-Worker sind verbindlich.

Alle Einstellungen tragen das Präfix `SLAYER_APP_`: `BUNDLE_DIR=build/pilot-v1`, `WORK_DIR=build/work`, `HOST=127.0.0.1`, `PORT=8000`, `ALLOWED_HOSTS=127.0.0.1:*,localhost:*`, `ALLOWED_ORIGINS=http://127.0.0.1:*,http://localhost:*`, optional `GATEWAY_BEARER_TOKEN`, `QUERY_TIMEOUT_SECONDS=15` (1–60), `STARTUP_TIMEOUT_SECONDS=30` (1–120). Host-/Originlisten sind kommasepariert und müssen zum Gateway passen. Der Token schützt nur MCP; Probes bleiben erreichbar. Tokens über die Laufzeitumgebung injizieren.

Die Compose-Einrichtung bindet den Streamable-HTTP-MCP-Endpunkt automatisch in OpenWebUI an. Der Agent verwendet zuerst `search`, dann `inspect`, anschliessend `analyse` mit `arguments.request` (Beispiele unter `examples/requests/`). Er übernimmt geprüfte Codes, automatisch erzeugte Definitionen/Formeln, Hinweise und `cell_status`. Er erhält keinen SQL-/Modellpflegezugang. Der Dienst ruft selbst kein LLM auf.

Verbleibender Fachumfang: Jahresdaten, offene Quellen, belegte Marginalverteilungen. Geschlecht/Staatsangehörigkeit bleibt wegen des realen Schlüsselfehlers gesperrt; Steuern mit Gebietsstand 2026 und monatliche eBau-Daten sind inspizierbar, aber nicht queryfähig. Fahrzeugstichtage bleiben unbekannt. Keine Schätzung fehlender Kreuzverteilungen, keine automatische Datenkorrektur, kein Cache und keine Warteschlange.

## Lesereihenfolge

1. `AGENTS.md`: verbindliche Arbeitsweise und Grenzen für den Coding-Agenten.
2. `spec/00_ZIEL_UND_ENTSCHEIDUNGEN.md`: Umfang und bewusste Vereinfachungen.
3. `spec/01_VERTRAEGE.md`: vollständige Ein- und Ausgaben der Werkzeuge.
4. `spec/02_SEMANTIK_UND_COMPILER.md`: fachliche Regeln und Übersetzung in SLayer.
5. `spec/03_MODULE_KLASSEN_METHODEN.md`: Dateien, Zuständigkeiten und Methodensignaturen.
6. `spec/04_DATEN_UND_ABNAHME.md`: echte Testdaten, Datenfehler und ausführbare Abnahmekriterien.
7. `spec/05_BETRIEB_UND_UMSETZUNG.md`: Logging, Container, Ressourcen und Umsetzungsschritte.

`STARTPROMPT.md` enthält den Startauftrag für einen Coding-Agenten. Die Spezifikationsdateien unter `spec/` sind normativ. Beigefügte Messungen und Proben belegen konkrete Integrationsentscheidungen; sie sind keine bereits implementierte produktive Anwendung.

`examples/` enthält 19 strukturell geprüfte Analyseanfragen, ihre erwarteten fachlichen Ergebnisse beziehungsweise Ablehnungen, die DTO-Referenz, ein generiertes JSON-Schema und eine native Fahrzeugmodellvorlage mit `meta.analytics`. `PRUEFBERICHT.md` beschreibt den ursprünglichen Spezifikationsstand. [ABNAHME.md](ABNAHME.md) dokumentiert die abgeschlossene Anwendungsabnahme mit 132 bestandenen Tests und den konkreten Grenzen.

## Daten und Nachweise

Die Testdaten stammen aus den mitgelieferten Katalogverweisen. Die Original-Parquet-Dateien bleiben unverändert unter `tests/fixtures/real/raw/`. `manifest.json` dokumentiert URLs, Abrufzeit, Dateigrösse, SHA-256 und fachliche Zeitangaben. Die Tests benötigen nach der einmaligen Installation keine Netzwerkverbindung.

Die Quelle nach Geschlecht und Staatsangehörigkeit enthält einen realen Schlüsselfehler und bleibt als negative Fixture erhalten. Der Coding-Agent darf diesen Fehler nicht stillschweigend korrigieren. Die Lösung muss ihn erkennen und die betroffene optionale Quelle für Analysen sperren.

Der geprüfte technische Stand ist SLayer 1.4.1 am Commit `516539dfec2979180695efa4351e0adccd6b2816`. Die mitgelieferten Proben verwenden diesen Stand. Ein Versionswechsel ist eine gesonderte, anhand der Integrationsproben zu begründende Änderung.

## Ergebnis der Umsetzung

Die Umsetzung liefert einen startbaren Dienst, der über MCP sucht, Modelle beschreibt und zulässige Analysen berechnet. Der Nachweis erfolgt über die tatsächlichen Daten und die in der Spezifikation definierten Positiv-, Negativ- und Betriebsfälle. Ein Dokument, ein Mock oder ein ausschliesslich synthetischer Testlauf erfüllt diesen Auftrag nicht.
