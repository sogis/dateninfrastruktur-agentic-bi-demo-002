# Öffentliche Verträge

Dieses Dokument ist normativ. Alle Beispiele verwenden öffentliche fachliche IDs. Ein Client übergibt weder einen nativen SLayer-Modellpfad noch einen SQL-Ausdruck. Der Dienst erzeugt diese aus dem geprüften Katalog.

## 1 Die drei Werkzeuge

| Werkzeug | Signatur der Python-Funktion | Zweck |
|---|---|---|
| `search` | `async def search(query: str, limit: int = 10) -> CallToolResult` | Passende freigegebene Modelle und Kennzahlen finden |
| `inspect` | `async def inspect(model_id: str) -> CallToolResult` | Definitionen, verfügbare Dimensionen, Werte, Zeit-/Raumstand und Grenzen eines Modells lesen |
| `analyse` | `async def analyse(request: AnalysisRequest) -> CallToolResult` | Eine neue, strukturierte Analyse prüfen und berechnen |

Alle drei Werkzeuge sind lesend. MCP-Annotations: `readOnlyHint=true`, `destructiveHint=false`, `idempotentHint=true`, `openWorldHint=false`. `idempotentHint` beschreibt den unveränderlichen Datenstand; ein BUSY-Fehler bei einem späteren Aufruf bleibt möglich. Die Tools laufen über Streamable HTTP unter `/mcp`. Es gibt keine parallele öffentliche REST-Abfrage-API und keinen öffentlichen Endpunkt zur Modellpflege.

Das Analyseargument ist wegen der Funktionssignatur unter `arguments.request` verschachtelt. Alle nachfolgenden Analysebeispiele zeigen den Inhalt dieses `request`-Objekts. Das MCP-Schema MUSS mit dem tatsächlich registrierten Werkzeug übereinstimmen; nicht nur ein JSON-Schema als Dokument ablegen.

### 1.1 Gemeinsame Hülle

Erfolg:

```json
{"ok": true, "request_id": "server-generated-uuid", "catalog_version": "sha256:...", "data": {}}
```

Fachlicher oder betrieblicher Fehler:

```json
{
  "ok": false,
  "request_id": "server-generated-uuid",
  "catalog_version": "sha256:...",
  "error": {
    "code": "E_MODEL_UNAVAILABLE",
    "message": "Die Quelle ist wegen eines nicht eindeutigen Gemeindeschlüssels gesperrt.",
    "retryable": false,
    "details": {"model_id": "population_sex_nationality", "quality_code": "DUPLICATE_KEY"}
  }
}
```

`CallToolResult.structuredContent` enthält diese Hülle, `content` einen Textblock mit demselben JSON. Keine zweite abweichende Zusammenfassung. Bei Fehlern `isError=true`, bei Erfolg `false`. Fehler in MCP-/JSON-RPC-Nachrichten beziehungsweise durch FastMCP abgewiesene Argumente dürfen die standardisierte Protokoll-Fehlerantwort verwenden. Sobald die Anwendung den Aufruf bearbeitet, benutzt sie die obige Hülle.

Die Anwendung erzeugt `request_id`; ein Client kann keine Log-ID einschleusen. `catalog_version` ist ein stabiler SHA-256 über Modellbundle, Quellen-/Qualitätsmanifest und Semantikvertragsversion. Keine Startzeit in diesen Hash aufnehmen.

## 2 `search`

`query`: getrimmter Text, 2–300 Zeichen. `limit`: 1–20, Standard 10. Native lexikalische Suche über gepflegte deutsche Beschreibungen, Labels und Synonyme; keine Embeddings. Die Suche benötigt keinen Zugriff auf die analytische Datenbank.

`data` enthält:

```json
{
  "matches": [{
    "model_id": "vehicles",
    "metric_id": "vehicles.count",
    "label": "Fahrzeugbestand",
    "description": "Einzelne Fahrzeuge nach Gemeinde und Fahrzeugart.",
    "unit": "vehicles",
    "available_years": [2025],
    "dimensions": ["municipality", "district", "year", "vehicles.category", "vehicles.group"],
    "status": "ready",
    "notes": ["Konkreter Beobachtungsstichtag nicht dokumentiert."]
  }],
  "truncated": false
}
```

Nur abfragbare Modelle erscheinen als normale Treffer. Eine unbekannte Suchformulierung liefert eine leere Trefferliste. Eine Suche ist kein Fehler. Doppelte Treffer derselben Kennzahl werden entfernt. Native Scores dürfen intern zur Sortierung dienen; der öffentliche Vertrag verspricht keinen kalibrierten Relevanzwert. Für `truncated` wird ein Treffer mehr als angefordert beschafft, soweit die native Suche dies unterstützt.

## 3 `inspect`

`model_id` ist eine exakte veröffentlichte Modell-ID, maximal 80 Zeichen. Antwortfelder:

| Feld | Inhalt |
|---|---|
| `model_id`, `label`, `description` | Identität und fachliche Beschreibung |
| `status` | `ready`, `quarantined` oder `unavailable` |
| `status_reasons` | Strukturierte Qualitäts-/Umfangsgründe, ohne Stacktrace |
| `domain`, `population` | Kompatibilitätscodes, z.B. `municipal_annual`, `so_municipalities_v2025` |
| `period_kind`, `available_years` | Hier `year` und tatsächlich verfügbare Jahre |
| `reference_dates` | Beobachtungsstichtag je Jahr; unbekannt bleibt `null` |
| `metrics` | ID, Label, Definition, Einheit, `temporal_kind`, zulässige Aggregate, Dimensionen, Additivität |
| `dimensions` | ID, Label, Werttyp, gemeinsame oder faktlokale Dimension, Eigentümer |
| `values` | Vollständige, geprüfte Werte kleiner Dimensionen bis 200 Werte; Codes und Anzeigenamen getrennt |
| `coverage` | Bekannte Grundzellenabdeckung, belegte vollständige Kategorien, verbleibende Unsicherheit |
| `source` | Original-URL, Snapshot-SHA-256, Abrufzeit, Lizenzverweis, Herkunft der Zeitangaben |
| `examples` | Höchstens zwei kleine Beispiele im öffentlichen Analysevertrag |
| `rules` | Für das Modell relevante verständliche Regeln und Ablehnungsgründe |

Ein bekanntes gesperrtes Modell bleibt inspizierbar. Seine Kennzahlen sind nicht queryfähig. Eine unbekannte ID ergibt `E_UNKNOWN_MODEL`. Gespeicherte native SQL-Definitionen, lokale Datenbankpfade, freie native Joinpfade und nicht geprüfte Samples werden nicht veröffentlicht. Ein Label ist nie ein Ersatz für einen Code: Gemeinde Egerkingen hat in diesen Daten den Integer-Code `2401`; die Fahrzeugart Personenwagen hat den String-Code `"01"`.

## 4 Analyse-DTOs

Die folgende Definition ist ein verbindlicher Implementierungsentwurf für `contracts.py`. Kleine syntaktische Anpassungen an die gepinnte Pydantic-Version sind erlaubt; das öffentliche JSON bleibt gleich.

```python
from __future__ import annotations
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, FiniteFloat, StrictBool, StrictInt, StrictStr

class DTO(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True, frozen=True)

Scalar = StrictStr | StrictInt | FiniteFloat | StrictBool | None

class YearWindow(DTO):
    from_year: StrictInt
    to_year: StrictInt
    require_same_reference_date: StrictBool = False

class Predicate(DTO):
    field: str
    op: Literal["eq", "ne", "in", "not_in", "lt", "le", "gt", "ge", "between", "is_null", "not_null"]
    values: list[Scalar] = Field(default_factory=list)

class AggregateNode(DTO):
    kind: Literal["aggregate"]
    metric: str
    op: Literal["sum", "min", "max"] = "sum"
    where: list[Predicate] = Field(default_factory=list)
    grain: list[str] | None = None
    temporal_reduce: Literal["none", "mean_annual_totals"] = "none"

class ConstantNode(DTO):
    kind: Literal["constant"]
    value: StrictInt | FiniteFloat

class BinaryNode(DTO):
    kind: Literal["binary"]
    op: Literal["add", "subtract", "multiply", "divide"]
    left: Expr
    right: Expr
    scale: FiniteFloat = 1.0

class PeriodNode(DTO):
    kind: Literal["period"]
    op: Literal["shift", "fixed_year", "absolute_change", "relative_change"]
    value: Expr
    years: StrictInt | None = None
    year: StrictInt | None = None

Expr = Annotated[AggregateNode | ConstantNode | BinaryNode | PeriodNode, Field(discriminator="kind")]

class OutputSpec(DTO):
    id: str
    expr: Expr

class SortSpec(DTO):
    field: str
    direction: Literal["asc", "desc"] = "asc"

class AnalysisRequest(DTO):
    period: YearWindow
    group_by: list[str] = Field(default_factory=list)
    filters: list[Predicate] = Field(default_factory=list)
    outputs: list[OutputSpec]
    order_by: list[SortSpec] = Field(default_factory=list)
    limit: StrictInt = 100

for cls in (BinaryNode, PeriodNode, OutputSpec, AnalysisRequest):
    cls.model_rebuild()
```

Listen sind absichtlich JSON-Listen. Unter strikter Pydantic-Prüfung nicht versehentlich Tuple-Eingaben voraussetzen, wenn FastMCP bereits dekodierte Python-Listen übergibt. `frozen` verhindert Attributzuweisungen; zur wirklich unveränderlichen internen Darstellung Listen nach Prüfung in Tupel/Frozensets übernehmen oder konsequent nicht verändern. Keine Behauptung tiefer Unveränderlichkeit einer normalen Liste.

### 4.1 Zusätzliche Feldregeln

- `from_year <= to_year`, Jahre zwischen 1900 und 2100. Kein implizites «aktuelles Jahr».
- `group_by` enthält eindeutige Dimension-IDs. `year` ist die besondere gemeinsame Jahresdimension; Zeitfilter kommen ausschliesslich aus `period`.
- `outputs`: mindestens ein Ergebnis. `id` erfüllt `[a-z][a-z0-9_]{0,39}`, ist eindeutig und kollidiert nicht mit einer Gruppierungs-ID. Die ID dient nur dem Antwort-Mapping. Sie wird nicht als nativer Alias eingesetzt.
- `eq/ne/lt/le/gt/ge` haben genau einen Wert, `between` genau zwei geordnete Werte, `in/not_in` 1–100 Werte, `is_null/not_null` keine Werte. `None` ist nur bei den beiden expliziten NULL-Operatoren zulässig. Numerische Codes bleiben numerisch, Stringcodes bleiben Strings; keine automatische Umwandlung und keine Behandlung von `true` als Zahl 1.
- Prädikate derselben Liste sind mit UND verbunden. Eine ODER-Auswahl gleicher Dimension wird mit `in` ausgedrückt. Keine freie Boolesche Abfragesprache.
- Globale `filters` enthalten nur gemeinsame Raumdimensionen. `where` enthält ausschliesslich lokale Dimensionen des betreffenden Fakts. Gemeinsame Filter werden nicht in einzelnen Blättern überschrieben.
- `grain=null` verwendet das Ausgabegrain. Ein ausdrücklich gröberes Grain ist nur beim Divisionsnenner erlaubt. `grain=[]` bedeutet den Gesamtnenner innerhalb der gemeinsamen Filter, nicht das Ignorieren dieser Filter.
- `scale` ist nur bei `divide` ungleich 1 erlaubt, endlich und positiv, maximal 1’000’000. Geldumrechnung erfolgt über autorisierte Kennzahlen, nicht über eine vermeintliche Wechselkurskonstante.
- `shift`, `absolute_change`, `relative_change` verlangen `years` zwischen 1 und 10 und kein `year`. `fixed_year` verlangt nur `year`. Positives `years=1` bedeutet das Vorjahr. Verschachtelte PeriodNodes sind nicht erlaubt.
- `relative_change` liefert eine dimensionslose Änderung, z.B. `0.0765935`; die Metadaten kennzeichnen Prozentdarstellung. Ein Client zeigt dafür `7.65935 %` an. Keine zweite Multiplikation um 100 im Zahlenwert.
- `order_by` darf nur ausgegebene Dimensionen oder Output-IDs nennen. `limit` ist 1–1’000. Ein nicht vorhandenes Sortierfeld ist ein Fehler.
- Kein `label`, `source_model`, `formula`, `sql`, `variables`, `ModelExtension`, `dry_run`, `timeout` oder `role` im öffentlichen Request. Unbekannte Felder werden abgewiesen.

## 5 Verbindliche Budgets

| Grenze | Wert |
|---|---:|
| HTTP-Requestkörper | 65’536 Bytes |
| Öffentliche Outputs | 8 |
| Gruppierungsdimensionen | 6 |
| Ausdrucksknoten insgesamt über alle Outputs | 40 |
| Maximale Ausdruckstiefe | 8 |
| Prädikate insgesamt, global und lokal | 16 |
| Werte je `in/not_in` | 100 |
| Einzelner String-Filterwert | 256 Zeichen |
| Sichtbare Jahre | 10 |
| Zusätzlich benötigte Vergleichsjahre | 10 |
| Unterschiedliche interne Prüfausdrücke | 24 |
| Native Measures einschliesslich Hilfswerte | 48 |
| Vollständige interne Ergebniszeilen | 10’000 |
| Nativer Query-Limit zum Erkennen der Überschreitung | 10’001 |
| Öffentliche Ergebniszeilen nach Sortierung | 1’000 |
| Interne Worker-Ergebnisdatei / serialisierte öffentliche Tool-Hülle | 8 MiB / 2 MiB |
| Analyse einschliesslich Vorbereitung des Workers | 15 Sekunden |

Budgets sind lokale Settings, keine Anfrageparameter. Die 2 MiB beziehen sich auf die UTF-8-serialisierte `ToolEnvelope`, vor der MCP-Darstellung als Text und `structuredContent`. Beide Darstellungen zusammen dürfen nicht irrtümlich als 2 MiB Gesamt-Wiregrenze bezeichnet werden; die tatsächliche HTTP-Antwort ist durch Doppelrepräsentation und JSON-Escaping grösser. Der MCP-Integrationstest misst auch diese Grösse; Gateway-Limits sind darauf abzustimmen. Dafür wird kein zusätzlicher allgemeiner Streaming-Proxy implementiert. Grenzverletzung wird erklärt; der Dienst schneidet weder einen Formelbaum noch einen zur Berechnung benötigten Ergebnissatz still ab. Grössere konkrete Anforderungen sind ein begründeter Folgeentscheid.

## 6 Vollständige Analysebeispiele

### 6.1 Personenwagen und Motorräder je 1’000 Einwohner

```json
{
  "period": {"from_year": 2025, "to_year": 2025},
  "group_by": [],
  "outputs": [{
    "id": "selected_vehicles_per_1000",
    "expr": {
      "kind": "binary", "op": "divide", "scale": 1000,
      "left": {
        "kind": "aggregate", "metric": "vehicles.count",
        "where": [{"field": "vehicles.category", "op": "in", "values": ["01", "60"]}]
      },
      "right": {"kind": "aggregate", "metric": "population.count"}
    }
  }]
}
```

Sollwert: `649.6804637625776`. Fachlicher Hinweis zum unbekannten Fahrzeugstichtag ist obligatorisch. Mit `require_same_reference_date=true` wird diese Kombination zurückgewiesen. Für eine Ausgabe nach Fahrzeugart `group_by=["vehicles.category"]` verwenden und im Bevölkerungsnenner `grain=[]` setzen. Für Gemeinde und Art entsprechend `group_by=["municipality","vehicles.category"]`, Nennergrain `["municipality"]`.

### 6.2 Durchschnitt des jährlichen AV-Personalbestandes

```json
{
  "period": {"from_year": 2024, "to_year": 2025},
  "outputs": [{
    "id": "mean_staff",
    "expr": {"kind": "aggregate", "metric": "staff.count", "temporal_reduce": "mean_annual_totals"}
  }]
}
```

Sollwert `65.5`. Die einfache Summe über beide Jahre wird abgewiesen. Der Durchschnitt über die einzelnen Ausbildungszeilen wäre `13.1` und ist falsch für diese Frage.

### 6.3 Veränderung des nominalen Umsatzes je Mitarbeiter

```json
{
  "period": {"from_year": 2025, "to_year": 2025},
  "outputs": [{
    "id": "revenue_per_staff_change",
    "expr": {
      "kind": "period", "op": "relative_change", "years": 1,
      "value": {
        "kind": "binary", "op": "divide",
        "left": {"kind": "aggregate", "metric": "revenue.nominal_chf"},
        "right": {"kind": "aggregate", "metric": "staff.count"}
      }
    }
  }]
}
```

Der Compiler muss 2024 mit einlesen, obwohl nur 2025 ausgegeben wird. Der Sollwert entspricht ungefähr `0.0931564863521` beziehungsweise `9.31564863521 %`. Eine Analyse darf dieses Verhältnis nicht als kausale Produktivitätswirkung oder als inflationsbereinigten Umsatz bezeichnen.

## 7 Analyseergebnis

`data` enthält `rows`, `columns`, `outputs`, `notices`, `cell_status`, `visible_period`, `truncated`, `matched_rows` und `provenance`.

```json
{
  "rows": [{"cars_per_1000": 574.0563189016005}],
  "columns": [{"id": "cars_per_1000", "kind": "float", "nullable": true}],
  "outputs": [{
    "id": "cars_per_1000",
    "label": "Personenwagen je 1000 Einwohner",
    "nature": "calculated",
    "unit": "vehicles/persons",
    "scale": 1000,
    "grain": [],
    "canonical_expression": "1000 * sum(vehicles.count; vehicles.category in ['01']) / sum(population.count)",
    "sources": ["vehicles", "population"],
    "reference_dates": {"vehicles": {"2025": null}, "population": {"2025": "2025-12-31"}}
  }],
  "notices": [{"code": "SAME_REPORTING_YEAR_REFERENCE_DATE_UNKNOWN", "source": "vehicles", "message": "Vergleich im Berichtsjahr 2025; der Fahrzeugstichtag ist nicht dokumentiert."}],
  "cell_status": [],
  "visible_period": {"from_year": 2025, "to_year": 2025},
  "truncated": false,
  "matched_rows": 1,
  "provenance": {"source_snapshots": [{"source_id": "vehicles", "sha256": "..."}], "slayer_version": "1.4.1", "semantic_contract": "1.0"}
}
```

Darstellungsvorschriften:

- Einfache Summen von Zählwerten bleiben Integer. Ein Jahresmittel oder eine nicht ganzzahlige Skalierung eines Zählwerts darf Float ergeben; der Ergebnistyp folgt dem Operator. Geldsummen sind Dezimalstrings mit zwei Nachkommastellen, beispielsweise `"2762610.00"`, mit `columns.kind="decimal"`; die Berechnung verwendet DECIMAL, keine Textrechnung. Verhältnisse sind endliche Floats. Datumswerte sind ISO-Daten. `NaN`/Infinity sind niemals gültiges JSON-Ergebnis.
- Gruppenschlüssel sind Codes. Kleine zusätzliche `labels`-Mappings dürfen Codes lesbar machen, ohne das Gruppieren über stabile Schlüssel zu verändern. Keine Joins über Anzeigenamen.
- Labels und `canonical_expression` werden aus dem geprüften Ausdruck erzeugt. Ein Alias wie `frauen_65_plus` gibt einem Ergebnis nicht diese fachliche Bedeutung. Freie Arithmetik hat `nature="calculated"`.
- `cell_status` enthält nur problematische Zellen: `{"row_key":{"municipality":2401},"output":"cars_per_1000","code":"ZERO_DENOMINATOR"}`. Bei Gesamtergebnissen ist `row_key={}`. Keine Statusmeldung pro normaler Zelle.
- `truncated` bedeutet ausschliesslich, dass das öffentliche `limit` einen vollständig berechneten, geprüften Ergebnissatz kürzt. `matched_rows` ist dessen sichtbare Zeilenzahl vor dem öffentlichen Limit. Interne Überschreitung von 10’000 Zeilen ist dagegen ein Fehler ohne Daten.
- Keine Datenzeilen ergeben einen erfolgreichen leeren Ergebnissatz mit `NO_MATCHING_DATA`, keinen erfundenen Nullbestand. Ein vorhandener Nullbestand ist numerisch `0`; ein unbekannter Wert ist `null` mit Grund.
- Ergebnisse werden deterministisch sortiert: angeforderte Sortierung, NULL immer zuletzt, danach Gruppenschlüssel als stabile Tie-Breaker. Bei fehlender Sortierung aufsteigend nach Gruppenschlüsseln. Geldstrings werden für den Sortiervergleich als Decimal interpretiert.

## 8 Fehlerkatalog

Es gibt genau eine eigene Exception `AnalysisError(code, message, details=None, retryable=False)`. Keine Exception-Klasse pro Fehlercode. Fehlerdetails dürfen IDs und kurze sichere Kontextangaben enthalten, keine SQL-Texte, Tokens, beliebige Dateipfade oder vollständige Eingaben.

| Bereich | Codes |
|---|---|
| Vertrag | `E_INVALID_REQUEST`, `E_QUERY_TOO_COMPLEX`, `E_UNKNOWN_MODEL`, `E_UNKNOWN_METRIC`, `E_UNKNOWN_DIMENSION` |
| Verfügbarkeit | `E_MODEL_UNAVAILABLE`, `E_PERIOD_UNAVAILABLE`, `E_UNSUPPORTED_PERIOD`, `E_INCOMPATIBLE_POPULATION` |
| Fachliche Kombination | `E_GLOBAL_FILTER_NOT_SHARED`, `E_CROSS_CLASSIFICATION_UNAVAILABLE`, `E_AGGREGATION_NOT_ALLOWED`, `E_NON_ADDITIVE_DIMENSION`, `E_TIME_AGGREGATION_NOT_ALLOWED`, `E_GRAIN_MISMATCH`, `E_REFERENCE_ONLY_DENOMINATOR`, `E_UNIT_MISMATCH` |
| Operatoren | `E_UNSUPPORTED_PRODUCT`, `E_UNSUPPORTED_DENOMINATOR`, `E_ZERO_CONSTANT_DENOMINATOR`, `E_UNSUPPORTED_TEMPORAL_COMPOSITION`, `E_UNSUPPORTED_FIXED_BASE_SERIES` |
| Zeitbezug | `E_REFERENCE_DATE_UNKNOWN`, `E_REFERENCE_DATE_MISMATCH` |
| Engine/Grösse | `E_NATIVE_PLAN_UNSUPPORTED`, `E_RESULT_TOO_LARGE`, `E_ENGINE_FAILURE`, `E_WORKER_PROTOCOL` |
| Betrieb | `E_BUSY`, `E_TIMEOUT`, `E_NOT_READY`, `E_INTERNAL` |

Nur `E_BUSY` ist standardmässig `retryable=true` und enthält einen kurzen Hinweis, später erneut anzufragen. Ein Timeout fordert zuerst eine einfachere Analyse; kein automatischer sofortiger Wiederholungszyklus. Fachliche Fehler werden durch einen angepassten Request behoben. Der Dienst repariert sie nicht stillschweigend.
