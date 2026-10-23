# OpenWebUI-Komplettpaket: Abnahme vom 23. Oktober 2026

Das Paket startet mit `./start.sh`. OpenWebUI ist unter **http://localhost:3003**, MCP unter **http://127.0.0.1:8003/mcp** erreichbar. Beide Compose-Dienste bleiben lokal gestartet. Die Anmeldung verwendet die aus Demo 001 übernommene lokale `.env`; Zugangsdaten stehen nicht in diesem Bericht.

Verwendet wird [OpenWebUI v0.12.3](https://github.com/open-webui/open-webui/releases/tag/v0.12.3), der zum Prüfzeitpunkt neueste stabile Release, gepinnt auf:

```text
ghcr.io/open-webui/open-webui:v0.12.3@sha256:a537bbe1e6b428820f52ed4a029d7fff97062e24d5cf32c365fba36fd0542def
```

Das bisherige 122B-Modell aus Demo 001 war beim übernommenen Infomaniak-Zugang nicht mehr verfügbar. Gemäss ausdrücklicher Auswahl wurde **Qwen/Qwen3.8-27B-FP8** verwendet. Der Start prüft auch die tatsächliche Verfügbarkeit des Basismodells; eine vorhandene Workspace-Modellkarte allein genügt nicht als Nachweis.

## Nachweise

| Prüfung | Ergebnis |
|---|---|
| Gesamte Fach- und Betriebsabnahme | **144 Tests bestanden**, 55,57 Sekunden, keine Fehler/Skips. F01–F16, N01–N17, M01–M09 und B01–B15 einschliesslich tatsächlicher Query-Prozessbeendigung, BUSY, Cleanup, Quarantäne und strukturierten Logs. |
| Abschliessende Einrichtungstests | **12 Tests bestanden**, 0,77 Sekunden. Einschliesslich nach dem Gesamtlauf ergänzter Prüfung, dass nur korrelierte Werkzeugantworten als Live-Nachweis gelten. Damit sind 145 unterschiedliche Tests ausgeführt. |
| Imagebau und eingebettetes Bundle | Authoring im Docker-Build aus Originaldateien und nativen Modellen. Keine lokale Projektinstallation und kein Host-Bundle für Compose erforderlich. B15 prüft sowohl eingebettetes als auch gemountetes Bundle. |
| Container | Unprivilegiert, Read-only-Root, Netzwerk `none` im B15-Test, eine CPU, 1 GiB RAM, 256 MiB Arbeitsbereich; echter MCP-F04-Aufruf und Exit 0. Eingebettete Variante mit UID 12345, 297,2 MiB gemessenem Spitzenspeicher inklusive Testclient. |
| Compose-Konfiguration | Eigenes Projekt und WebUI-Volume, Loopbackports 3003/8003, MCP-UID 10001, keine Provider-Zugangsdaten im MCP-Container. Beide Dienste healthy. Readiness steuert den WebUI-Start. |
| WebUI-API | Anmeldung erforderlich, Registrierung/Ollama/Folgefragen aus. Provider und Basismodell verfügbar, native Modellkarte voreingestellt. WebUI verifiziert selbst genau **search, inspect, analyse**. |
| MCP über Compose-Port | Echte SDK-Verbindung liefert F04 **649.6804637625776** und `SAME_REPORTING_YEAR_REFERENCE_DATE_UNKNOWN`. |
| OpenWebUI → Infomaniak → MCP → SLayer | Frischer endgültiger F04-Chat: zwei search-, zwei inspect- und ein analyse-Aufruf. Exakter Sollwert in der tatsächlichen Werkzeugantwort, Anzeige **649.68** mit ausdrücklich unbekanntem Fahrzeugstichtag. |
| Fachliche Ablehnung durch denselben Chatweg | N02 mit `require_same_reference_date=true`: **E_REFERENCE_DATE_UNKNOWN**. Die Chatantwort erklärt die Ablehnung und lockert die Bedingung nicht. |
| Browser | Admin-Anmeldung, voreingestelltes Modell **Agentic BI – SLayer**, lesbare F04-Antwort und Stichtaghinweis. CSS aus Demo 001 geladen, berechneter Textskalierungsfaktor **1.07**. |
| Wiederholter Start | Alle sechs zum abschliessenden Neustartzeitpunkt vorhandenen Chats erhalten; keine doppelte verwaltete MCP-Verbindung. Lokale Zugangsdaten und Demo-001-Konfiguration unverändert, kopiertes CSS bytegleich. Weitere Abnahmechats liegen im eigenen Volume. |
| Geheimnisausschlüsse | `.env` mit `0600`, von Git ignoriert; tatsächlicher Docker-Buildversuch `COPY .env` scheitert am ausgeschlossenen Kontext. Provider-Token und Signaturschlüssel fehlen in allen nicht ignorierten Repositorydateien. HTTP-Fehlertexte geben keine Response-Bodies mit möglichen Zugangsdaten aus. |
| Daten | Alle neun Original-Hashes erneut bestätigt. Quelldateien, Modelle, Sollzahlen, öffentlicher Analysevertrag und Kernmodule unverändert. |

Maschinenlesbare Belege: [Abnahmestand](evidence/openwebui/acceptance.json), [Gesamtlauf](evidence/openwebui/regression.xml), [abschliessende Einrichtungstests](evidence/openwebui/setup-tests.xml), [Konfiguration](evidence/openwebui/configuration.json), [Live-Fälle](evidence/openwebui/live.json), [Chatantworten](evidence/openwebui/chat-answers.json), [korrelierte MCP-Logs](evidence/openwebui/mcp-events.json), [Persistenz](evidence/openwebui/persistence.json), [Deployment und Geheimnisausschlüsse](evidence/openwebui/deployment.json), [Container](evidence/openwebui/embedded-container.json), [Compose-MCP](evidence/openwebui/compose-mcp.json), [Browserbild](evidence/openwebui/browser-f04.jpg). Die Live-Request-IDs sind in den tatsächlichen MCP-Abschlusslogs enthalten; Modelltext allein gilt nicht als Zahlenbeleg.

## Kleine Anpassungen und Grenzen

Es bleiben acht fachliche/betriebliche Python-Module, drei Werkzeuge und höchstens ein aktiver Query-Unterprozess. Hinzu kommt ausschliesslich das Einrichtungsskript mit Python-Standardbibliothek; keine zusätzliche Produktklasse oder Python-Runtime-Abhängigkeit. OpenWebUI bringt seine eigene Infrastruktur im offiziellen Image mit. Cube, Java und R-Lab wurden nicht übernommen.

OpenWebUI v0.12.3 ergänzt beim Speichern Modellmetadaten. Der Einrichtungsvergleich prüft daher die explizit verwalteten Felder. Native MCP-Fehler erscheinen in dieser Version als zusätzliche Fehlerhülle; der Live-Prüfer liest die tatsächlich zugehörige Toolantwort. Der analytische Vertrag wird weder gelockert noch durch eine zweite Berechnung ersetzt.

Das gewählte Modell erzeugte während der Erprobung zusätzliche ungültige Output-Felder und wiederholte einen fehlerhaften Aufruf bis zum Provider-Ratelimit. Der unveränderte strikte MCP-Vertrag wies diese Anfragen ab. Die endgültige Konfiguration verlangt minimale gültige Outputs, Abbruch bei Schemafehlern und mindestens zwei Nachkommastellen für Verhältnisse. Die tatsächlich im Image vorhandene Einstellung `CHAT_RESPONSE_MAX_TOOL_CALL_ITERATIONS=8` begrenzt die native Werkzeugschleife. Der abschliessende frische F04-Chat war ohne fehlerhaften Toolaufruf erfolgreich. Das ist keine Garantie für beliebige natürlichsprachliche Fragen; Modellfehler, Provider-Verfügbarkeit und Ratelimits bleiben möglich.

Die bisherigen Fachgrenzen gelten weiter: Geschlecht/Staatsangehörigkeit quarantiniert, Steuer-Geografie 2026 und eBau-Monatsdaten gesperrt, Fahrzeugstichtag unbekannt, keine erfundenen Kreuzverteilungen. Demo 002 besitzt einen eigenen WebUI-Datenbestand ohne Chatmigration aus 001. Da Cookies keine Ports unterscheiden, können mehrere lokale WebUIs mit demselben Hostnamen kollidieren; unterschiedliche Browserprofile oder Hostnamen verwenden. Die Live-Prüfung benötigt den externen Provider und verursacht dessen reguläre Nutzungskosten. Es wurde kein Dienst extern veröffentlicht.
