# Betrieb, Lieferumfang und Umsetzung

## 1 Reproduzierbare technische Basis

Die unten aufgeführten Versionen wurden für diese Ausarbeitung tatsächlich verwendet. Sie bilden den ersten Implementierungsstand, keine Aussage, jede spätere Version sei ungeeignet.

| Bestandteil | Geprüfter Stand |
|---|---|
| Python | 3.12.14 |
| motley-slayer | 1.4.1, Commit `516539dfec2979180695efa4351e0adccd6b2816` |
| DuckDB | 2.0.0 |
| duckdb-engine | 0.17.0 |
| SQLAlchemy | 2.0.55 |
| SQLGlot | 30.24.0 |
| Pydantic | 2.14.1 |
| MCP Python SDK | 1.30.0 |
| Starlette / Uvicorn | 1.9.0 / 0.54.0 |
| AnyIO | 4.15.1 |

`evidence/requirements-tested.txt` hält die vollständige Forschungsumgebung fest. Daraus die notwendigen Runtime- und Testabhängigkeiten in `pyproject.toml` bestimmen und einen verbindlichen `uv.lock` erzeugen. Nicht unbesehen sämtliche Forschungspakete zur Produktionsabhängigkeit machen. Keine SLayer-Extras `[all]`, keine Embeddingpakete und keine Java-/JDBC-Abhängigkeiten für diesen Dienst installieren. DuckDB und der benötigte native Suchpfad sind im geprüften SLayer-Stand vorhanden.

SLayer per unveränderlichem Commit referenzieren, beispielsweise als direkte Git-Abhängigkeit oder als daraus gebautes internes Wheel mit Herkunftsangabe. Ein beweglicher `main`-Branch erfüllt den Pin nicht. Build-/Installationszeit darf Netz benötigen; Runtime und normale Tests danach nicht. Keine Paketupdates oder Extensiondownloads beim Dienststart.

Der Quellstand nennt MIT als SLayer-Lizenz. Die mitgelieferten Daten nennen ihre eigene Lizenz-URI im Quellenmanifest. Bei Weitergabe der Anwendung die erforderlichen Hinweise der eingebundenen Pakete und Daten erhalten; dafür keine zusätzliche Lizenzverwaltungsplattform entwickeln.

## 2 Datenbundle und Betriebsrechte

Ein Betriebsbundle enthält `pilot.duckdb`, die geprüften nativen Modelle mit `meta.analytics`, Quellen-/Schema-/Qualitätsmanifest und die für den dokumentierten Prüfpfad benötigten lokalen Quellnachweise. Alle Dateinamen sind fest. Ein Agent kann weder eine Datenbank noch einen Bundlepfad wählen.

Das Bundle wird schreibgeschützt eingebunden. Neue Daten werden in einem neuen Verzeichnis vorbereitet, geprüft und mit neuer Bundle-ID geladen. Kein In-place-Update der aktiven Datei, kein Hot Reload und keine selbst veränderten Runtime-Memories. Im Pilot genügt ein Neustart mit dem neuen freigegebenen Stand; kein Rollout-Orchestrator im Anwendungscode.

SLayer-Storage und jeder Queryprozess erhalten eine private beschreibbare Arbeitskopie der Modelle, weil YAMLStorage Sidecars erzeugen kann. Die eigentliche Datenbank bleibt dieselbe schreibgeschützte Datei. Arbeitsdateien sind temporär und nach Prozessende zu entfernen.

### 2.1 Geprüfte DuckDB-Konfiguration

```python
url = sqlalchemy.engine.URL.create(
    "duckdb", database=str(database_path),
    query={
        "access_mode": "READ_ONLY",
        "threads": "1",
        "memory_limit": "256MB",
        "temp_directory": str(work_dir / "duckdb-tmp"),
        "enable_external_access": "false",
        "autoload_known_extensions": "false",
        "autoinstall_known_extensions": "false",
        "allow_unsigned_extensions": "false",
    },
)
datasource = DatasourceConfig(
    name="pilot", type="duckdb", database=str(database_path),
    connection_string=url.render_as_string(hide_password=False),
)
```

Die Optionen wurden über die tatsächliche native SLayer-/SQLAlchemy-Datasource geprüft: SUM funktioniert, CREATE wird abgewiesen. Kein Connector-Monkeypatch nötig. Die Datenbank enthält physische Tabellen, sodass externer Zugriff für normale Queries nicht erforderlich ist. `work_dir / "duckdb-tmp"` ist das zuvor angelegte private temporäre Verzeichnis des jeweiligen Workers. Ohne diese ausdrückliche Option würde DuckDB standardmässig neben der schreibgeschützten Datenbank ein Tempverzeichnis vorsehen. Temporäres Spilling bleibt mit der Option im begrenzten Arbeitsvolume. `memory_limit` ist eine DuckDB-Grenze, kein vollständiges RAM-Limit des ganzen Pythonprozesses; dafür gilt zusätzlich das Containerlimit.

## 3 Ein Prozess pro Analyse

Ein neuer Query-Unterprozess benötigt in den kleinen durchgeführten Proben insgesamt etwa **1.00, 1.21 und 1.28 Sekunden**. Folgeabfragen in einem schon warmen Prozess lagen bei etwa 51 ms. Die Messung stammt aus dieser Arbeitsumgebung und ist kein produktives SLA.

Für V1 wird der begrenzte Startaufwand akzeptiert. Dadurch entfallen Pool, Warteschlange, Wiederverwendungszustand, Verbindungsreste und eine Worker-Neustartzustandsmaschine. Wenn spätere reale Messungen einen warmen Worker rechtfertigen, ist das ein konkreter Folgeentscheid.

Der Gesamtzeitraum einer Analyse beträgt standardmässig 15 Sekunden und beginnt **vor** dem Unterprozessstart. Der OS-Alarm wird vor schweren Workerimports gesetzt. Der Supervisor beendet bei Ablauf die komplette Prozessgruppe und bestätigt das Prozessende. Ein tatsächlich laufendes DuckDB-CPU-Statement wurde so beendet; zusätzlich wurde der eigene Worker-Alarm nachgewiesen. `asyncio.wait_for` allein ist kein ausreichender Abbruchbeleg.

Ein Analyseslot pro Serverprozess, Uvicorn mit einem Worker, eine Containerreplik. Weitere Anfragen erhalten sofort `E_BUSY`. Keine skalierbare globale Slotverwaltung bauen, solange die eine Replik genügt. Such-/Beschreibungsaufrufe bleiben während einer Analyse verfügbar.

## 4 Container und OpenShift

Ein Dockerfile genügt. Freigegebenes Python-3.12.14-Basisimage beim tatsächlichen Build nach Digest pinnen; keinen nicht geprüften Digest in diese Spezifikation erfinden. Installation aus dem Lockfile. Start mit `python -m slayer_app.server`.

Die Anwendung muss mit nicht privilegierter beziehungsweise von OpenShift zugewiesener UID arbeiten. Keine Abhängigkeit von einem beschreibbaren Benutzerhome oder einer festen Root-UID. Bundle read-only, Arbeitsverzeichnis als begrenztes Volume, keine zusätzlichen Linux-Capabilities. Die normale Anwendung braucht nach dem Build keinen ausgehenden Internetzugriff.

Initiale Betriebsannahme: 1 CPU, 1 GiB RAM, begrenztes temporäres Arbeitsvolume von 256 MiB, eine Replik. Diese Werte mit den realen Abnahmen messen. Falls ein Memorylimit eine ansonsten korrekte Abfrage beendet, den Fehler sichtbar behandeln und die gemessenen Ressourcen begründet anpassen; kein stilles unbegrenztes Profil.

Health-/Readiness-Probes verwenden `/healthz` und `/readyz`. Ein normal belegter Slot ist kein Grund, den Pod aus dem Service zu nehmen. Nicht bestätigtes Prozessende nach einem Kill ist dagegen ein harter Fehler: keine neue Analyse, Readiness falsch, kontrollierter Neustart.

Ein kleines Deployment-Beispiel darf geliefert werden. Keine Helmchart-Hierarchie, kein Operator und keine Terraformplattform für diesen Pilot. Tatsächliche Veröffentlichung beziehungsweise Installation in einer fremden Laufzeitumgebung benötigt den entsprechenden separaten Auftrag; die lokale Containerabnahme gehört bereits zum Implementierungsauftrag.

## 5 Zugang und Datenumfang

V1 verarbeitet ausschliesslich die freigegebenen offenen Daten. Ein vorhandenes Gateway kann den Zugriff vermitteln. Optional unterstützt die Anwendung einen festen Bearer-Diensttoken, konstantzeitlich geprüft; dieser Token ist keine Benutzerrolle und kein Datenscope. Ohne Tokenbindung standardmässig lokal lauschen beziehungsweise den Zugang im vorgesehenen internen Netz betreiben.

`ALLOWED_HOSTS` und `ALLOWED_ORIGINS` werden explizit konfiguriert. Die vorhandene MCP-Hostprüfung nicht pauschal abschalten. TLS liegt beim vorhandenen Gateway. Keine neue OAuth-, Mandanten- oder Rollenverwaltung, keine RLS-Imitation im Prompt.

Vertrauliche Quellen, personenbezogene Detaildaten und Benutzerrechte sind nicht Bestandteil dieses Datenpakets. Ihre spätere Aufnahme wäre ein neuer Fach-/Berechtigungsvertrag. Die für offene Daten getroffene Vereinfachung darf dann nicht als bereits vorhandene Zugriffskontrolle ausgegeben werden.

## 6 Logging und Fehlerbehandlung

Eine JSON-Zeile pro Ereignis. Mindestfelder für Analyseabschluss: `event`, UTC-Zeit, `request_id`, `catalog_version`, verwendete Modell-/Kennzahl-IDs, Dauer, Anzahl intern berechneter und öffentlich gelieferter Zeilen, Kürzung, Erfolg/Fehlercode. Start-/Qualitätsereignisse enthalten Anzahl verfügbarer/gesperrter Quellen und sichere Fehlercodes.

Nicht loggen: Bearertoken, vollständige natürliche Benutzerfrage, komplette Filterwerte, generiertes SQL, Datenbankconnectionstrings, vollständige Ergebnisse oder rohe native Exceptions mit eingebettetem SQL. Ungefiltertes Uvicorn-Accesslog deaktivieren. Ein Fehlerklassenname und eine Request-ID genügen für den öffentlichen Fehlerpfad; ausführlichere gezielte Debugausgabe ist nur lokal mit kontrollierten Testdaten erlaubt.

Fachliche Fehler werden als `AnalysisError` in eine kleine strukturierte Toolantwort umgesetzt. Unerwartete Fehler erhalten einen generischen sicheren Fehlercode und die Request-ID. Keine automatische Abfragewiederholung und keine eigenmächtige Abschwächung einer Fachregel, damit doch noch ein Ergebnis erscheint.

## 7 Agentenverhalten und OpenWebUI-Integration

Der Analyseagent erhält kurze Werkzeugbeschreibungen und die folgenden Regeln in seinem System-/Toolkontext:

1. Zuerst passende Modelle suchen und ihre Kennzahlen/Dimensionen prüfen.
2. Codes aus `inspect` verwenden, insbesondere Stringcodes mit führender Null. Bei mehreren plausiblen Interpretationen die relevante Unklarheit benennen oder nachfragen.
3. Die Benutzerfrage in einen neuen Ausdruck gemäss Vertrag übersetzen; keine Auswahl aus fest verdrahteten Fragefunktionen.
4. Ausgabehinweise und `cell_status` in der Antwort erhalten. Ein NULL nicht als 0 formulieren, einen unbekannten Stichtag nicht verschweigen.
5. Systemgenerierte Definition/Formel als fachliche Grundlage verwenden. Ein freier Alias oder eine natürlichsprachliche Behauptung ersetzt die beobachtete Datenstruktur nicht.
6. Bei Ablehnung die konkrete Grenze erklären. Einen nicht beobachteten Schnitt nicht über Produkte oder frei erfundene Joinregeln schätzen.

Dies sind Verhaltenshinweise für gute Antworten; die verbindlichen Prüfungen liegen im Dienst. Es gibt keine Verpflichtung, ein neues Agentenframework zu bauen oder das LLM innerhalb dieses Dienstes selbst aufzurufen. Das bestehende LLM-/OpenWebUI-System konsumiert die drei MCP-Werkzeuge.

Die konkrete installierte OpenWebUI-Anbindung ist im Zielsystem zu prüfen. Aus der verifizierten Streamable-HTTP-Unterstützung des MCP Python SDK wird nicht automatisch die Kompatibilität jeder vorhandenen UI-Version abgeleitet. Für die lokale Abnahme genügt ein echter MCP-Client, zusätzlich ist der vorgesehene Agentenpfad zu dokumentieren. Ein SSE-Zusatztransport wird nur gebaut, wenn der konkrete vorhandene Client ihn tatsächlich benötigt; kein vorsorglicher Doppeltransport.

## 8 Vertikaler Umsetzungsplan

Kein geschätztes Kalenderversprechen und kein generiertes Frameworkgerüst vor dem ersten funktionierenden Datenweg. Die Reihenfolge ist verbindlich, die Anzahl Commits nicht.

### Schritt 1 — Reale Basis und ein vollständiger Datenweg

Projekt und Lockfile anlegen. Hashes und Normalisierung der mitgelieferten Daten prüfen. Zunächst Bevölkerung/Fahrzeuge mit den tatsächlichen nativen Modellen laden. Ein minimaler Analysevertrag soll über Compiler und native Engine die korrekte Bevölkerungssumme sowie F04 berechnen. Erwartete Werte direkt aus dem unabhängigen Oracle vergleichen. Keine Arbeit an zusätzlichen Plattformkomponenten.

**Fertig, wenn:** F01/F04 real bestehen und der unbekannte Fahrzeugstichtag sichtbar bleibt.

### Schritt 2 — Vollständiger Vertrag und Fachgrenzen

Vier Ausdruckstypen, Metadatenindex, Grain-/Einheiten-/Additivitätsregeln, lokale Filter und gröbere Nenner implementieren. Jahresmittel und Zeitvergleich ergänzen, interne Ergebnisprüfungen einschliesslich verschobener Guards verbinden. AV- und GWS-Modelle hinzufügen. Reale Quarantänequelle und die Scopefälle Steuern/eBau beschreiben.

**Fertig, wenn:** F01–F16, N01–N17 und die relevanten Mutationsfälle bestehen; keine Zahlenberechnung in Python als Ersatz für SLayer.

### Schritt 3 — Prozess- und Transportgrenzen

Einzelnen transienten Worker, Deadline, OS-Alarm, Cleanup, BUSY und Grösse implementieren. FastMCP/Starlette mit genau drei Tools verdrahten. Health/Readiness, optionalen Token und strukturierte Logs ergänzen. Globale Startup-Lifespan genau einmal.

**Fertig, wenn:** B01–B14 einschliesslich tatsächlich beendetem DuckDB-Prozess und echtem MCP-F04 bestehen.

### Schritt 4 — Autorverfahren und Containerabnahme

`author build/verify`, unveränderliche Bundle-Versionen und Betriebs-README fertigstellen. Einen Container mit den vorgesehenen UID-/Dateirechten bauen und die echte Abfrage durch diesen Container ausführen. Relevante Laufzeit-/Speichermessungen protokollieren. Offene Fehler beheben, dann die vollständige verpflichtende Matrix einmal ausführen.

**Fertig, wenn:** B15 und der Gesamtabschlussbericht vorliegen. Keine optionale Plattformausweitung beginnen, während ein verpflichtender Daten-/Fachfall fehlt.

## 9 Erwartete Bedienbefehle der fertigen Anwendung

Diese Befehle sind Zielverträge für den Coding-Agenten, keine Behauptung, das Spezifikationspaket enthalte bereits die Anwendung:

```bash
uv sync --frozen
uv run python -m slayer_app.author build --manifest tests/fixtures/real/manifest.json --models models --output build/pilot-v1
uv run python -m slayer_app.author verify --bundle build/pilot-v1
SLAYER_APP_BUNDLE_DIR=build/pilot-v1 SLAYER_APP_WORK_DIR=build/work uv run python -m slayer_app.server
uv run pytest
```

Umgebungsvariablen einheitlich mit `SLAYER_APP_` präfixieren: `BUNDLE_DIR`, `WORK_DIR`, `HOST`, `PORT`, `ALLOWED_HOSTS`, `ALLOWED_ORIGINS`, `GATEWAY_BEARER_TOKEN`, `QUERY_TIMEOUT_SECONDS`, `STARTUP_TIMEOUT_SECONDS`. Das README zeigt konkrete lokale Defaults und ein Containerbeispiel. Es schreibt keine echten Tokens in Beispieldateien.

## 10 Abschlusslieferung des Coding-Agenten

Erwartet werden startbarer Quellcode in den acht vorgesehenen Modulen, native Modelle, reproduzierbarer Lock, Authoringbefehle, reale und gezielte Negativtests, Dockerfile, ein kurzes Betriebs-README und ein Testbericht mit den stabilen Abnahme-IDs.

Der Testbericht unterscheidet bestanden, fehlgeschlagen und begründet noch nicht geprüft. Er nennt die verwendeten Rohhashes, den tatsächlichen SLayer-Commit, die Paketversionen, den Containerstand und die relevanten Laufzeitgrenzen. Er erklärt jede zusätzliche Klasse oder Abhängigkeit und nennt tatsächlich verbleibende Grenzen. Ein blosses «Tests grün» ohne Bezug auf die echten Daten und die negative Fachabnahme genügt nicht.

## 11 Spätere Optionen — kein Auftrag in Version 1

Monats-/Quartalsverträge für eBau, historisierte Geografiebrücken, Freigabe einer korrigierten Geschlecht-/Nationalitätsquelle, vertrauliche Daten mit wirksamen Berechtigungen, zusätzliche Datenbanken, ein warmer Worker, Ergebnis-Caching, beliebige native Query-DAGs und eine Modellpflegeoberfläche bleiben gesonderte Folgeaufträge. Erst einen konkreten Bedarf und dessen kleinstmöglichen Ausbau formulieren; keine leeren Erweiterungspunkte vorsorglich einbauen.

## Primärquellen

- [SLayer am geprüften Commit](https://github.com/MotleyAI/slayer/tree/516539dfec2979180695efa4351e0adccd6b2816), insbesondere `pyproject.toml`, Storage-, Search-, Inspect- und Query-Engine-Code.
- [SLayer Python SDK](https://docs.motley.ai/slayer/getting-started/python/), [Datasources](https://docs.motley.ai/slayer/configuration/datasources/), [Search](https://docs.motley.ai/slayer/concepts/search/).
- [MCP Python SDK](https://github.com/modelcontextprotocol/python-sdk), zusätzlich die tatsächlich installierten Signaturen und ausgeführten Probe-Ergebnisse unter `evidence/runtime/`.
- Eigene Ausführungsnachweise unter `evidence/` und die dokumentierten Originaldaten unter `tests/fixtures/real/`.
