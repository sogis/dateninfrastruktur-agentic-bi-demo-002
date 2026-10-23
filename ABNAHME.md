# Anwendungsabnahme vom 23. Oktober 2026

Dieser Bericht dokumentiert die ursprüngliche Kernanwendung. Die anschliessende Docker-/OpenWebUI-Erweiterung samt erneuter Regression ist separat in [OPENWEBUI_ABNAHME.md](OPENWEBUI_ABNAHME.md) nachgewiesen.

Die konkrete Anwendung hat **132 Tests bestanden**, ohne Fehler oder übersprungene Tests. Gesamtlauf: 63,51 Sekunden. Ausgeführt mit:

```sh
uv sync --frozen
uv run pytest -q --tb=short --junitxml=build/acceptance.xml -o junit_family=xunit1
```

Maschinenlesbare Nachweise: [Abnahme und Paketstände](evidence/application/acceptance.json), [JUnit-Ergebnisse](evidence/application/acceptance.xml), [Containerprüfung](evidence/application/container.json). Die älteren Proben unter `evidence/native_real`, `evidence/semantics` und `evidence/runtime` bleiben Forschungsnachweise; der vorliegende Bericht beschreibt die implementierte Fassade.

## Verbindliche Matrix

| Fälle | Ergebnis | Nachweis |
|---|---|---|
| F01–F07 | Bestanden | Bevölkerung 293’081; alle 106 Gemeinden, zehn Bezirke und 42 Fahrzeugarten vollständig verglichen; lokale Auswahl 01/60 liefert 649.6804637625776 je 1’000 Einwohner bei unverändertem Bevölkerungsnenner. Führende Null erhalten. |
| F08–F13, F16 | Bestanden | Personal 66/65, exakte Umsatzstrings 2’566’066.00/2’762’610.00, Jahresmittel 65.5; Jahresfluss-Summe, native Zeitverschiebung und zusammengesetztes Wachstum einschliesslich verborgener Vergleichsjahre. Ausbildung bleibt in der inneren Jahrespartition. |
| F14–F15 | Bestanden | Wärmepumpenanteile kantonal/nach Bezirk aus aggregierten Summen; gemeinsamer Raumfilter auf allen Blättern. |
| N01–N17 | Bestanden | Gesperrte Quellen, unbekannte Stichtage, falsche globale Filter, fehlende Kreuzverteilungen, Bestands-Zeitsummen, Produkte/verschachtelte Nenner, Einheiten, Grain und Zeitkomposition werden geschlossen behandelt. Irreführende Output-IDs ändern weder Definition noch Formel. |
| M01–M09 | Bestanden | Reale abgeleitete Fixtures und kleine ausdrücklich abgeleitete DB-Kopien: doppelte Schlüssel, Nullnenner, fehlende Gemeinden/Jahre, verschobene Abdeckung, leere Auswahl und sichere Stringliterale. Unabhängige Outputs bleiben erhalten. |
| B01–B04 | Bestanden | Echter MCP-SDK-Client über TCP/Streamable HTTP: initialize, tools/list, tools/call; genau search/inspect/analyse und tatsächliches verschachteltes Schema. F04 durch echten Worker und native Engine. Quarantäne bleibt ready; fehlerhafte Kernquelle ergibt ready 503 bei erreichbarer Healthroute. |
| B05–B09 | Bestanden | Ein Slot und sofort BUSY; echte lange DuckDB-CPU-Abfrage durch SIGKILL beendet und geerntet, Folgeanalyse möglich; eigener SIGALRM ohne Supervisor; Cancellation/Shutdown und wiederholter Abbruch bereinigen vor Slotfreigabe. Unbestätigtes Prozessende sperrt Readiness und neue Analysen. Fehlerhafte Workerantworten bleiben sicher und werden entfernt. |
| B10–B14 | Bestanden | Tatsächlich 10’000/10’001 native Gruppen, öffentliche Limits erst danach; Knoten-/Tiefen-/Prädikatbudgets; HTTP 413, 2-MiB-Hülle/8-MiB-Datei; native Offline-/Read-only-Datasource einschliesslich abgewiesenem CREATE. JSON-Logs und optionaler konstantzeitlich geprüfter Token. |
| B15 | Bestanden | Lokaler Linux/arm64-Container mit UID 12345, CapEff=0, Read-only-Root und -Bundle, beschränktem Arbeitsvolume, Netzwerkmodus none. Readiness, Quarantänebeschreibung, echter MCP-F04-Aufruf und Shutdown mit Exit 0. |

Zusätzliche Tests prüfen unter anderem stabile Katalogversionen, vollständigen Hashindex, typisierte Codes, unveränderte Literalwerte, unerwartete native Warnungen, nicht endliche Ergebnisse, numerische Geldsortierung, NULL zuletzt, Datentypen bei leeren Ergebnissen und einen expliziten Bezirksnenner pro Gemeinde. Kein Integrationstest ersetzt die SLayer-Berechnung durch einen Mock; kontrollierte Antwort- und Prozessfehler werden nur in abgegrenzten Fehlertests eingespeist.

## Daten- und Laufzeitstand

Alle neun Original-SHA-256 stimmen mit dem unveränderten [Quellenmanifest](tests/fixtures/real/manifest.json) überein; die tatsächlich geprüften Hashes stehen auch in `evidence/application/acceptance.json`. Originaldateien und gespeicherte Sollwerte wurden nicht verändert. Die 18 gelieferten Baseline-Invarianten melden jeweils null Verletzungen. Die reale negative Quelle hat weiterhin 106 Zeilen und nur 104 eindeutige Gemeindeschlüssel, darunter dreimal 2525. Sie wird weder korrigiert noch in der Query-Storage registriert.

Python **3.12.14**, SLayer **1.4.1** aus Commit **516539dfec2979180695efa4351e0adccd6b2816**. Die im Auftrag genannten Referenzstände von DuckDB, SQLAlchemy, SQLGlot, Pydantic, MCP, Starlette, Uvicorn und AnyIO sind unverändert gepinnt; alle transitiven Pakete stehen in `uv.lock`.

Final vorbereitetes lokales Bundle: `build/acceptance-final`. Katalogversion:

```text
sha256:97e1b9312013c478f42df45e67f4661d0a37f4441245b0b3ab419d6dde4bbbd4
```

Start im vorhandenen Workspace:

```sh
SLAYER_APP_BUNDLE_DIR=build/acceptance-final SLAYER_APP_WORK_DIR=build/work uv run python -m slayer_app.server
```

Endpoint: `http://127.0.0.1:8000/mcp`; Health/Readiness unter `/healthz` und `/readyz`. Neubau-, Prüf- und Containerbefehle sowie sämtliche Umgebungsvariablen stehen im [README](README.md).

Eine Analyse benötigt einen frischen Prozess. Standardfrist 15 Sekunden vor Prozessstart, OS-Alarm vor schweren Imports, zusätzlich zwei Sekunden bestätigtes Cleanup; kein freier Slot vor bestätigtem Prozessende. Weitere feste Grenzen: 65’536 Requestbytes, 40 Knoten, Tiefe 8, acht Outputs, 10’000 interne Ergebniszeilen, 1’000 öffentliche Zeilen, DuckDB ein Thread und 256 MiB Speichergrenze.

Die finale HTTP-Antwort für MCP-F04 umfasste **2’752 Bytes**. Die 2-MiB-Dienstgrenze gilt für die einfache Tool-Hülle; Text plus structuredContent vergrössern die tatsächliche Wireantwort. Gatewaygrenzen müssen dies berücksichtigen.

Containerbasis: `python:3.12.14-slim@sha256:f77ac9e44ae96ef2c90b8053ea08c31f8be030f824196b0ae4db6d462c84e51f`. Getestetes Image: `sha256:0a85b19273660dae086944945519dcd6e156f205c1f32ebc6cef29ba5a352e91`. Mit 1 CPU, 1 GiB RAM und 256 MiB Arbeitsvolume: Readiness nach 3,23 Sekunden, F04 in 1,89 Sekunden, cgroup-Spitzenspeicher **354’496’512 Bytes (338,1 MiB)** inklusive des im Container laufenden Testclients. Dies sind lokale Einzelmessungen, kein produktives SLA.

## Kleine technische Anpassungen

- `SlayerModel` besitzt im geprüften Paket kein natives Label-Feld. Modelltitel stehen in `meta.analytics.label`; native Beschreibungen enthalten die Suchsynonyme. Spalten verwenden ihr vorhandenes natives Label.
- Native Ergebnisse verwenden `wurzel.spalte` als Schlüssel. Die Fassade bildet diese geprüften Schlüssel auf öffentliche IDs ab.
- SLayer 1.4.1 erkennt die Zeichenfolge `OVER(` auch innerhalb eines Stringliterals als Window-Funktion. Der AST-Serializer kodiert ausschliesslich betroffene Stringtokens als semantisch identische Unicode-Escapes und prüft beide ASTs sowie den nativen Parser. Der Integrationstest rechnet mit genau diesem Literal; weder Validator noch Engine werden gepatcht.
- Ein kleiner Eventloop-Timer weckt die native Thread-Rückgabe auf macOS. Er verändert weder Plan noch Rechnung. Direkte Tests verwenden das vorhandene öffentliche `engine_factory.reset_cache()` zur Isolation zurückgehaltener synchroner Pools; produktive Queryprozesse enden nach jedem Auftrag.

Es bleiben genau die acht vorgesehenen Python-Module und die vorgesehenen Verhaltensklassen/DTOs/Datenträger. **Keine zusätzliche Produktklasse, kein Zusatzmodul und keine zusätzliche Runtime-Architekturabhängigkeit** wurden eingeführt. PyYAML wird für native Modellmetadaten direkt deklariert; es gehört bereits zur SLayer-Paketbasis. Hatchling 1.29.0 ist ausschliesslich das gepinnte Python-Buildbackend. Pytest, pytest-asyncio und HTTPX dienen der ausführbaren Abnahme. Ruff wurde einmalig als Formatierungs-/Prüfwerkzeug verwendet und gehört nicht zur Anwendung.

## Verbleibende Grenzen

Der Nachweis gilt für das eingefrorene Jahresdatenpaket und den kleinen veröffentlichten Ausdrucksvertrag. Die Geschlechts-/Nationalitätsquelle bleibt quarantiniert; Steuern mit Geografie 2026 und eBau-Monatsdaten bleiben nicht verfügbar. Fahrzeugstichtage sind unbekannt; unvollständige Kategorieverteilungen werden nicht zu Nullbeständen ergänzt. Das System liefert keine geschätzten gemeinsamen Merkmalsverteilungen und prüft keine beliebige natürlichsprachliche Interpretation.

Der Dienst verarbeitet offene Daten, unterstützt einen optionalen Diensttoken und eine Replik mit einem Worker. Rollen/RLS, vertrauliche Daten, historische Geografiebrücken, Monats-/Quartalsanalyse, Caching, Queue und freie native Queries sind nicht enthalten. Die ursprüngliche Kernabnahme prüfte den MCP-Agentenpfad mit einem echten SDK-Client; die spätere OpenWebUI-Abnahme ist im oben verlinkten Ergänzungsbericht dokumentiert. Es wurde kein Dienst extern veröffentlicht.
