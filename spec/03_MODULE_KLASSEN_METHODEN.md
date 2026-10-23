# Module, Klassen und Methoden

## 1 Zielstruktur

Der nachfolgende Baum beschreibt die **zu implementierende Anwendung**. Das gelieferte Spezifikationspaket enthält bereits die Dokumente, Fixtures und Forschungsnachweise; es behauptet nicht, diese Anwendung sei schon gebaut.

```text
pyproject.toml
uv.lock
Dockerfile
README.md
src/slayer_app/
    __init__.py
    config.py
    contracts.py
    catalog.py
    semantics.py
    author.py
    worker.py
    runtime.py
    server.py
models/
    <native SLayer-YAML mit meta.analytics>
tests/
    test_authoring.py
    test_semantics.py
    test_real_queries.py
    test_runtime.py
    test_mcp.py
    fixtures/real/
```

Die zwei wesentlichen Verhaltensklassen sind `SemanticCompiler` und `Runtime`. Dazu kommen DTOs und kleine Datenträger. Die genaue Zahl der DTOs ist kein Architekturziel; entscheidend ist, dass es keine Schichten und Klassen ohne konkrete Aufgabe gibt. Insbesondere keine Klassen `PopulationService`, `VehicleRepository`, `RatioStrategy` oder `AggregationFactory` einführen.

## 2 `config.py`

### `Settings`

Eingefrorene Dataclass. Felder: `bundle_dir: Path`, `work_dir: Path`, `host: str`, `port: int`, `allowed_hosts: tuple[str,...]`, `allowed_origins: tuple[str,...]`, `gateway_token: str | None`, `query_timeout_seconds: float = 15`, `startup_timeout_seconds: float = 30`. Die festen Query-/Ergebnisbudgets aus Dokument 01 stehen als Konstanten in derselben Datei; kein zusätzliches Konfigurationssystem.

### `load_settings() -> Settings`

Liest die dokumentierten Umgebungsvariablen. Löst lokale Pfade auf, prüft Pflichtverzeichnisse und den Wertebereich der Zeitlimits. Betreibergrenze für Queryfrist: 1–60 Sekunden. `work_dir` darf nicht innerhalb des schreibgeschützten Datenbundles liegen. Erstellt nur das eigene Arbeitsverzeichnis, niemals ein fehlendes Datenpaket. Kein Download, kein Katalogimport und kein Netzwerktest. Fehlerhafte Konfiguration beendet den Start mit verständlichem Fehlerstatus.

`gateway_token` darf nie in `repr(Settings)`, Logs oder Fehlermeldungen erscheinen; dafür das Dataclass-Feld mit `repr=False` kennzeichnen. Beim Start `SLAYER_USAGE_REPORTING=off` und `DO_NOT_TRACK=1` setzen, bevor SLayer importiert wird.

## 3 `contracts.py`

Enthält die DTOs aus Dokument 01 und die folgenden gemeinsamen Datenträger. Response-Dictionaries dürfen durch wenige TypedDicts dokumentiert werden; keine Klasse für jeden Hinweis, jede Zeile oder jede Quellenart.

### `AnalysisError`

```python
class AnalysisError(Exception):
    def __init__(self, code: str, message: str,
                 details: dict | None = None, *, retryable: bool = False): ...
```

Trägt ausschliesslich sichere strukturierte Informationen. Übersetzt keine fremden Fehlermeldungen ungeprüft in öffentliche Antworten. Der Exception-Text ist keine Quelle für Kontrollfluss; der Aufrufer verwendet `code`.

### `ToolEnvelope`

DTO für `ok`, `request_id`, `catalog_version`, `data` beziehungsweise `error`. Genau einer der beiden Payloads ist gesetzt; beim Serialisieren wird der andere weggelassen. Hilfsfunktionen:

```python
def success(request_id: str, catalog_version: str, data: dict) -> ToolEnvelope: ...
def failure(request_id: str, catalog_version: str | None, error: AnalysisError) -> ToolEnvelope: ...
```

### `WorkerJob`

```python
class WorkerJob(DTO):
    protocol_version: Literal[1]
    operation: Literal["validate", "analyse"]
    request_id: str
    deadline_monotonic_ns: int
    bundle_dir: str
    catalog_version: str
    allowed_model_ids: list[str]
    request: AnalysisRequest | None
```

`request` ist nur bei `analyse` gesetzt. Bundlepfad, Modellliste und Deadline stammen vom Elternprozess. Dieses Format ist kein öffentliches Werkzeug. Dateipfade sind keine Agentenargumente. Keine Klassen-/Objektserialisierung per pickle.

## 4 `catalog.py`

### `CatalogSnapshot`

Eine eingefrorene Dataclass mit `catalog_version`, `bundle_dir`, `database_path`, `models`, `metrics`, `dimensions`, `roots`, `sources`, `quality` und `allowed_model_ids`. `models` enthält die nativen `SlayerModel`-Objekte; die anderen Felder sind abgeleitete unveränderliche Sichten. Sie enthalten stabile öffentliche IDs und bereits aufgelöste native Pfade. Ein kleiner Mapping-Datenträger genügt je Kennzahl/Dimension; keine Vererbung pro Datentyp.

Nicht serialisierbare native Services bleiben ausserhalb dieses Snapshots in `Runtime`. Ein Worker lädt denselben versionierten Snapshot erneut von den Dateien. Es wird kein komplettes Objektgraph-Pickle zwischen Prozessen übertragen.

### `load_catalog(bundle_dir: Path) -> CatalogSnapshot`

**Eingabe:** lokales unveränderliches Bundle mit Datenbank, Modellen, Quellenmanifest und Qualitätsergebnis. **Ausgabe:** geprüfter struktureller In-Memory-Index. Liest Dateien, aber führt keine Agentenabfrage aus.

Prüft eindeutige öffentliche IDs, bekannte Metaschlüsseltypen, identifizierbare native Referenzen, vorhandene technische Spalten, kompatible Wurzeln und eindeutige Joinpfade. Stimmt Manifestversion und Bundle-ID ab. Bekannte gesperrte Quellen bleiben im Statusindex; ihre nativen Modelle werden nicht als ausführbar freigegeben. Ein strukturell beschädigtes Kernbundle führt zu `E_NOT_READY`.

### `check_data(catalog: CatalogSnapshot) -> dict`

Führt die begrenzte Qualitätsprüfung in einem internen Validate-Worker beziehungsweise im Authoring aus. Rückgabe: `ready`, `source_status`, `violations`, `warnings`, tatsächliche Zeilen-/Schlüsselzahlen, verfügbare Jahre, kleine Kategorienlisten, belegte `complete_values` und Hashes. Verwendet die expliziten Invarianten aus Dokument 04. Keine dynamische SQL-Generierung aus Clientwerten; Tabellen und Spalten stammen aus den geprüften Modellen.

Schema, Primärschlüssel, Pflicht-NULLs, unzulässige Orphans und Summenidentitäten sind harte Fehler. Eine fehlende Grundzelle bei sonst gültigem Fakt wird als Abdeckungslücke dokumentiert; sie wird zur Laufzeit über die Ergebnisprüfung sichtbar und nicht zu einer künstlichen 0. Eine gesamte erforderliche Quelle ohne nutzbare Daten verhindert Readiness. Optionale Quellen mit Schlüsseldefekten sind `quarantined`.

Der vorbereitete Bericht wird beim Build erzeugt; der Start prüft dessen Verbindung zu den tatsächlich eingebundenen Dateien und die Kerninvarianten erneut. Runtime-Validate und Authoring verwenden dieselbe Funktion. Das unveränderte fehlerhafte Parquet darf für den Quarantänenachweis als ausdrücklich benannte lokale Eingabe gelesen werden. Die eigentliche Query-Datasource bleibt immer offline/read-only.

### `make_storage(catalog: CatalogSnapshot, work_dir: Path) -> YAMLStorage`

Erstellt eine **private** beschreibbare Kopie ausschliesslich freigegebener nativer Modelle. `YAMLStorage` erzeugt Sidecars und kann Formate migrieren; deshalb nie unmittelbar auf dem unveränderlichen Bundle initialisieren. Setzt eine fest erzeugte lokale DuckDB-Datasource mit den Optionen aus Dokument 05. Kein übernommener Remote-Connection-String aus einer Benutzerdatei.

Eine asynchrone Variante `async def make_storage(...)` ist zulässig, falls die geprüften nativen Save-Methoden verwendet werden. Die Aufrufer müssen dann konsistent `await` benutzen; keine verschachtelten `asyncio.run()` im laufenden Eventloop.

### `search_catalog(...)` und `describe_catalog(...)`

```python
async def search_catalog(catalog: CatalogSnapshot,
                         service: SearchService,
                         query: str, limit: int) -> dict: ...
async def describe_catalog(catalog: CatalogSnapshot,
                           service: InspectService,
                           model_id: str) -> dict: ...
```

Native Konstruktoren: `SearchService(storage=..., engine=None, retrievers=[BM25Retriever(), TantivyRetriever()])` und `InspectService(storage=..., engine=None)`. Explizite Retrieverliste verhindert den standardmässigen Embedding-Retriever. Verwende die tatsächlich vorhandenen Methoden:

```python
await search_service.search(question=query, max_results=limit + 1, compact=True)
await inspect_service.inspect(reference=native_model_reference, entity_type="model",
                              format="json", show_sql=False, num_rows=0)
```

Native Resultate werden auf die öffentliche Positivliste abgebildet und um Fachregeln ergänzt. Keine ungeprüfte Weitergabe des gesamten nativen JSON. Für `quarantined`/`unavailable` antwortet `describe_catalog` aus dem Statusindex, ohne das Modell in der Query-Storage zu registrieren. Kategorien stammen aus dem Authoring-Bericht; Discovery löst keine Liveprofilierung aus.

## 5 `semantics.py`

### Interne Datenträger

```python
@dataclass(frozen=True)
class ExprInfo:
    unit: tuple[tuple[str, int], ...]
    grain: frozenset[str]
    metrics: frozenset[str]
    required_years: tuple[int, ...]
    is_constant: bool
    nature: Literal["aggregated", "calculated"]

@dataclass(frozen=True)
class ResultCheck:
    kind: str
    aliases: tuple[str, ...]
    expected: int | None
    outputs: tuple[str, ...]

@dataclass(frozen=True)
class CompiledExpression:
    node: ast.expr
    info: ExprInfo
    checks: tuple[ResultCheck, ...]

@dataclass(frozen=True)
class CompiledAnalysis:
    native_query: SlayerQuery
    output_manifest: tuple[dict, ...]
    result_checks: tuple[ResultCheck, ...]
    display_years: tuple[int, ...]
    native_years: tuple[int, ...]
    year_result_key: str | None
    remove_year: bool
    request: AnalysisRequest
    policy_notes: tuple[dict, ...]
```

Eine private veränderliche `CompileContext`-Dataclass hält nur den aktuellen Request, effektives Grain, feste Wurzel, Jahresmodus, Aliaszähler, generierte Measures und den Deduplizierungsindex. Sie ist kurzlebig pro `compile`-Aufruf. Kein globaler Compilerzustand über Requests hinweg.

### `SemanticCompiler`

```python
class SemanticCompiler:
    def __init__(self, catalog: CatalogSnapshot): ...
    def compile(self, request: AnalysisRequest) -> CompiledAnalysis: ...
    def _validate_request(self, request: AnalysisRequest) -> None: ...
    def _compile_expr(self, expr: Expr, ctx: CompileContext,
                      *, role: str) -> CompiledExpression: ...
    def _compile_aggregate(self, expr: AggregateNode, ctx: CompileContext,
                           *, role: str) -> CompiledExpression: ...
    def _compile_binary(self, expr: BinaryNode, ctx: CompileContext) -> CompiledExpression: ...
    def _compile_period(self, expr: PeriodNode, ctx: CompileContext,
                        *, role: str) -> CompiledExpression: ...
    def _predicate_ast(self, predicate: Predicate, ctx: CompileContext,
                        *, owner: str | None) -> ast.expr: ...
    def _add_check(self, kind: str, expressions: tuple[ast.expr, ...],
                    ctx: CompileContext, *, outputs: tuple[str, ...],
                    expected: int | None = None) -> ResultCheck: ...
    def check_native_response(self, compiled: CompiledAnalysis,
                                response: SlayerResponse) -> None: ...
    def finalize(self, compiled: CompiledAnalysis,
                   response: SlayerResponse) -> dict: ...
```

Methodenverträge:

| Methode | Konkrete Aufgabe und Nachbedingung |
|---|---|
| `__init__` | Behält nur den geprüften Katalog. Keine DB-Verbindung, kein Netz, keine Suchanfrage. |
| `compile` | Führt den Ablauf aus Dokument 02 aus. Entweder ein ausführbarer nativer Plan plus alle Hilfsprüfungen oder ein `AnalysisError`; keine teilweise freigegebene Query. |
| `_validate_request` | Zählt den gesamten Baum und prüft globale Grenzen, doppelte IDs, Filter-Arity, Jahrmodus und fachliche Verfügbarkeit. Keine Änderung am Request. |
| `_compile_expr` | Dispatch über genau vier `kind`-Werte, sonst Schemafehler. Reicht Rollen-/Zeitkontext ausdrücklich weiter. |
| `_compile_aggregate` | Prüft Quelle, Aggregator, lokale Dimensionen, Additivität, Grain und Zeitreduktion; erzeugt bedingtes natives Aggregat und seine Quellen-/Jahreschecks. |
| `_compile_binary` | Prüft Units, Operandrollen und die engen Nenner-/Produktgrenzen; erzeugt AST, vereint Abhängigkeiten und registriert den nativen Nennercheck. |
| `_compile_period` | Ermittelt benötigte Jahre; reicht bei shift/fixed_year die Operandrolle an das enthaltene Aggregat weiter, damit ein explizit gröberer Nenner zulässig bleibt; erzeugt native Verschiebung/Änderung und verschiebt alle zugehörigen internen Checks. Keine Berechnung vorheriger Werte in Python. |
| `_predicate_ast` | Prüft exakt typisierte Dimensionwerte und erstellt literale AST-Knoten. `owner=None` bedeutet global und shared; ein Faktowner erlaubt nur dessen faktlokale Dimensionen. |
| `_add_check` | Dedupliziert nach strukturellem AST, Grain und Zeitkontext, erzeugt sichere `hN`-Aliase und führt die Outputabhängigkeiten zusammen. Budgetprüfung vor Aufnahme. |
| `check_native_response` | Prüft strukturierte Warnungen und erwartete native Struktur. Für Dry-run noch keine Datenzeilen verlangen. Fehler vor eigentlicher Ausführung stoppen. |
| `finalize` | Wendet ausschliesslich die Ergebnisfreigabe-/Darstellungsschritte aus Dokument 02 an. Liefert das Analyse-`data`-Objekt aus Dokument 01. |

Reine Hilfsfunktionen für Units, AST-Referenzen, sichere Serialisierung, Count von Knoten und deterministische Sortierung bleiben in derselben Datei. Keine eigene Klasse dafür.

## 6 `author.py`

```python
def build_bundle(source_manifest: Path, models_dir: Path, output_dir: Path) -> dict: ...
def verify_bundle(bundle_dir: Path) -> dict: ...
def main() -> int: ...
```

`build_bundle` prüft die Original-SHA-256, erstellt eine neue physische DuckDB-Datei in einem neuen Zielverzeichnis, verwendet die expliziten Normalisierungen des Fixture-Builders, übernimmt die geprüften Modelle und schreibt Quellen-/Schema-/Qualitätsmanifest. Keine automatische Katalogmigration und keine beliebige Transformations-DSL. Bestehendes Ziel wird nicht überschrieben; ein neuer Bundle-Stand ist ein neues Verzeichnis.

Vor Veröffentlichung des Verzeichnisses werden technische Invarianten geprüft. Ein obligatorischer Kernfehler ergibt einen erfolglosen Build. Der reale optionale Schlüsselfehler wird als Quarantäne aufgenommen, sodass der übrige Pilot nutzbar bleibt. Quellen original bewahren; keine Korrektur anhand von Namensähnlichkeit.

`verify_bundle` prüft Hashes, Schema, Metadaten, native Modellvalidierung und Datenqualität eines bestehenden Pakets. Es schreibt keine Quelldaten um. CLI:

```bash
uv run python -m slayer_app.author build --manifest tests/fixtures/real/manifest.json --models models --output build/pilot-v1
uv run python -m slayer_app.author verify --bundle build/pilot-v1
```

Der Fixture-Builder im Spezifikationspaket ist eine nutzbare Vorlage für die festen Datenableitungen. Keine allgemeine ETL-Plattform daraus machen.

## 7 `worker.py`

```python
def main() -> int: ...
async def run_job(job: WorkerJob, job_dir: Path) -> ToolEnvelope: ...
def write_result(path: Path, envelope: ToolEnvelope, *, public: bool) -> None: ...
```

`main` liest den kleinen internen Job zunächst mit Standardbibliothek und Grössengrenze, entnimmt die monotone Deadline und setzt **vor schweren Imports** den OS-Alarm. Erst danach Pydantic/SLayer importieren und den Job vollständig validieren. Der Alarm benutzt `SIGALRM` mit `SIG_DFL` und `setitimer(ITIMER_REAL, remaining)`. Ist keine Zeit übrig, Exit 124. Zielplattform Linux.

`run_job` lädt den exakten Bundle-Stand, prüft die erlaubten Modelle gegen den eigenen Qualitätsindex und erstellt eine private Storage. Bei `validate` wird `check_data` ausgeführt. Bei `analyse`:

```python
compiler = SemanticCompiler(catalog)
compiled = compiler.compile(job.request)
engine = SlayerQueryEngine(storage=storage)
try:
    preview = await engine.execute(compiled.native_query, dry_run=True, cache=False)
    compiler.check_native_response(compiled, preview)
    response = await engine.execute(compiled.native_query, cache=False)
    compiler.check_native_response(compiled, response)
    data = compiler.finalize(compiled, response)
finally:
    await engine.aclose()
```

Das native `execute` bietet die gezeigten Argumente im geprüften Stand. Query-Caching bleibt aus. Die Anwendung importiert keine privaten Engine-Planungsmethoden.

`write_result` serialisiert eine endliche JSON-Hülle, prüft bei `analyse` (`public=True`) die 2-MiB-Grenze der öffentlichen Tool-Hülle und bei `validate` (`public=False`) die 8-MiB-Grenze der internen Datei. Es schreibt im privaten Jobverzeichnis eine temporäre Datei und ersetzt `result.json` atomar. Ein Fehler beim Schreiben führt zu einem definierten unerwarteten Workerexit. Der Elternprozess liest niemals ein noch laufend beschriebenes Resultat. stdout wird kein Datenkanal. Kein unbeschränktes `communicate()` mit kompletten Debugausgaben.

Ein fachlicher Fehler mit korrekt geschriebenem Envelope darf Exit 0 haben. Timeout ist Exit 124 oder Beendigung durch SIGALRM/Supervisor. Unerwarteter Exit ohne gültige Antwort wird vom Elternprozess als `E_ENGINE_FAILURE` beziehungsweise `E_WORKER_PROTOCOL` gemeldet. Keine rohen Tracebacks in die Antwort schreiben.

## 8 `runtime.py`

### `Runtime`

```python
class Runtime:
    def __init__(self, settings: Settings): ...
    async def start(self) -> None: ...
    async def search(self, query: str, limit: int) -> ToolEnvelope: ...
    async def inspect(self, model_id: str) -> ToolEnvelope: ...
    async def analyse(self, request: AnalysisRequest) -> ToolEnvelope: ...
    async def _run_worker(self, job: WorkerJob, job_dir: Path) -> ToolEnvelope: ...
    async def _terminate_and_reap(self, process: asyncio.subprocess.Process) -> None: ...
    async def aclose(self) -> None: ...
```

Zustand: Settings, `ready`, `closing`, Katalog, private Discovery-Storage, zwei native Discovery-Services und höchstens ein aktiver Prozess-/Jobeintrag. Kein Pool und keine Jobhistorie im Speicher. Ein kleines privates `ActiveJob`-Dataclass ist erlaubt; ein Prozesszustandsframework ist nicht nötig.

**`start`:** Katalog strukturell laden, einmaligen Validate-Worker mit Startupfrist starten, Ergebnis übernehmen, Discovery-Storage/Services aufbauen. Erst danach `ready=true`. Erwartete Katalog-/Datenqualitätsfehler intern übernehmen, den sicheren Grund speichern und regulär mit `ready=false` zurückkehren; so bleiben Health/Readiness erreichbar. Ein optionaler Quarantänefall verhindert Readiness nicht. Fehlerhafte Betriebskonfiguration und unerwartete Softwarefehler dürfen den ASGI-Start abbrechen; angelegte Ressourcen werden auch dabei bereinigt.

**`search`/`inspect`:** Bereitschaft und Eingabegrenzen prüfen, native DB-freie Services aufrufen und öffentliche Hülle erstellen. Sie belegen den Analyseslot nicht. Kein vollwertiger Query-Worker für eine Beschreibung.

**`analyse`:** Ohne `await` zwischen Prüfen und Setzen den einzigen Slot beanspruchen. Ein belegter Slot ergibt sofort `E_BUSY`; niemals auf einem Semaphore warten. UUID erzeugen, Deadline mit `time.monotonic_ns()` berechnen, privates Jobverzeichnis erzeugen, internen Job schreiben und `_run_worker` aufrufen. In jedem Ausgang genau ein Abschlusslog erzeugen.

**`_run_worker`:** `asyncio.create_subprocess_exec(sys.executable, "-m", "slayer_app.worker", "--job-dir", str(job_dir), start_new_session=True, ...)`. Kein Shellstring. Deadline einschliesslich Start-/Import-/Compilezeit anwenden. Nach Exit höchstens 8 MiB plus ein Prüfbyte aus der Antwortdatei lesen, Protokoll/Hülle und Request-/Katalog-ID prüfen. Verspätete Ergebnisse nach Deadline bleiben Timeout.

**`_terminate_and_reap`:** Bei Timeout, Cancellation oder Shutdown Prozessgruppe per `os.killpg(pid, SIGKILL)` beenden; `ProcessLookupError` bei bereits beendetem Prozess ist okay. Prozessende innerhalb einer zusätzlichen Cleanupfrist von zwei Sekunden bestätigen. Cleanup gegen äussere AnyIO-Cancellation abschirmen. Slot erst danach freigeben. Ist der Prozess nicht nachweislich beendet, Readiness zurücknehmen und kontrollierten Prozessneustart auslösen; keine zweite Analyse parallel starten.

**`aclose`:** `closing=true` und `ready=false`, aktive Arbeit beenden/ernten, laufende Discoveryaufrufe abschliessen beziehungsweise abbrechen und danach private Arbeitskopien entfernen. Native SearchService, InspectService und YAMLStorage besitzen im geprüften Stand keine öffentliche close/aclose-Methode; deren Referenzen freigeben, keine Methode erfinden. Die Query-Engine wird im Worker mit ihrem tatsächlich vorhandenen `aclose()` geschlossen. Mehrfacher Runtime-Cleanup soll harmlos sein. Keine neuen Analysen während Shutdown.

Ein HTTP-Verbindungsabbruch muss nicht zwingend sofort als Coroutine-Cancellation beim Server ankommen. Auch dann begrenzen Supervisor-Deadline und eigener Worker-Alarm die Arbeit. Kein unbelegtes Versprechen, jeder TCP-Abbruch werde sofort erkannt.

### Logging-Helfer

`configure_logging()` und `log_event(event: str, **safe_fields)` bleiben in `runtime.py`. Ein kleiner JSON-Formatter genügt. Nur erlaubte strukturierte Felder loggen; native Debug-/SQL-Logs unterdrücken. Keine neue Loggingplattform.

## 9 `server.py`

```python
def create_app(settings: Settings) -> Starlette: ...
def to_mcp(envelope: ToolEnvelope) -> CallToolResult: ...
def main() -> None: ...
```

`create_app` baut genau eine `Runtime`, eine FastMCP-Instanz und die drei Werkzeugfunktionen. Die externen Namen sind **search, inspect, analyse**. Keine mitgelieferten nativen Modell-/Datenquellen-Schreibtools registrieren. `to_mcp` bildet die Hülle unverändert auf Text und `structuredContent` ab.

Globale Initialisierung liegt in der äusseren Starlette-Lifespan:

```python
mcp = FastMCP(
    "Solothurn Datenanalyse", stateless_http=True, json_response=True,
    streamable_http_path="/mcp", max_request_body_size=65_536,
    transport_security=TransportSecuritySettings(
        allowed_hosts=list(settings.allowed_hosts),
        allowed_origins=list(settings.allowed_origins),
    ),
)
# Hier genau drei Tools registrieren.
mcp_app = mcp.streamable_http_app()

@asynccontextmanager
async def lifespan(app):
    try:
        await runtime.start()
        async with mcp.session_manager.run():
            yield
    finally:
        await runtime.aclose()

app = Starlette(
    routes=[Route("/healthz", health), Route("/readyz", ready), Mount("/", app=mcp_app)],
    lifespan=lifespan, max_body_size=65_536,
)
```

`streamable_http_app()` wird vor Zugriff auf `session_manager` aufgerufen. Sessionmanager genau einmal betreiben. Die FastMCP-Lifespan nicht für globale Kataloginitialisierung verwenden: Im stateless Modus wird eine Low-Level-Serverausführung pro HTTP-Request erzeugt. Eine Montage unter `/mcp` zusätzlich zum nativen Pfad würde versehentlich `/mcp/mcp` schaffen.

Health/Readiness: `/healthz` antwortet ohne DB-Abfrage 200, solange der Prozess ansprechbar ist. `/readyz` antwortet 200 nach erfolgreichem Kernstartup, sonst 503. Ein normal belegter Slot macht den Dienst nicht unready. Ein optionaler Tokencheck umschliesst nur die MCP-App; er lässt Healthrouten für die Containerprobes verfügbar.

`main` verwendet Uvicorn mit `workers=1`, `reload=False`, `access_log=False`, `log_config=None`, `proxy_headers=False`, `timeout_graceful_shutdown=5`. Bestehender Gatewayterminierung vertrauen nur soweit explizit konfiguriert; keine zusätzliche Authentifizierungsplattform implementieren.

## 10 Was ausdrücklich keine eigene Klasse benötigt

Einheitenvergleich, JSON-Hüllen, Quellhashprüfung, Knotenbudget, Literal-Serialisierung, Normalisierung der neun festen Dateninputs, Formatierung von Fehlern, Warnungscodes und Containerkonfiguration sind Funktionen, Dictionaries oder Dateien. Wenn während der Umsetzung eine weitere Klasse notwendig erscheint, muss der Abschlussbericht den konkreten verbleibenden Zustand oder die gekapselte Ressource nennen, die diese Klasse trägt. «Best practice» allein genügt nicht.
