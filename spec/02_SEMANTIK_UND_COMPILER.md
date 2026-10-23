# Semantik, Modellangaben und Compiler

## 1 Die kleine Eigenleistung

Die Anwendung besitzt einen Compiler für den in `01_VERTRAEGE.md` definierten Baum. Er prüft die dort möglichen Kombinationen und erzeugt native SLayer-Ausdrücke. SLayer übernimmt Auflösung der Modellbeziehungen, Voraggregation, SQL-Erzeugung und Ausführung. Ein allgemeiner Prüfer für frei eingesandte native SLayer-Queries wird nicht entwickelt.

Diese Grenze ist wesentlich: Die native Engine kann technisch mehr ausdrücken als der öffentliche Vertrag. Native Spaltenregeln und `to_many_handling="error"` allein genügen nicht, um beliebige Agentenformeln fachlich zu prüfen. Deshalb erzeugt die Anwendung ausschliesslich die nachfolgenden Formen. Sie bietet keine Hintertür über SQL, Variablen, Inline-Modelle, Modell-Erweiterungen, gespeicherte freie Formeln oder mehrere Abfragestufen.

## 2 Eine Quelle der Modellwahrheit

Die SLayer-YAML-Dateien enthalten die nativen Modelle und kleine zusätzliche Angaben unter `meta.analytics`. Ein `CatalogSnapshot` erschliesst diese Angaben beim Start. Es gibt keine daneben manuell gepflegte zweite Registry. Das erzeugte Qualitätsmanifest enthält beobachtete Befunde und Status, keine konkurrierenden Kennzahldefinitionen.

### 2.1 Native Modelle und Beziehungen

| Modell | Nativer Primärschlüssel | Beziehung zur gemeinsamen Wurzel |
|---|---|---|
| `municipalities` | `geo_version, municipality_id` | Geografische Dimension |
| `population` | `report_year, geo_version, municipality_id` | Wurzel für kommunale Jahresdaten; many-to-one zu `municipalities` über beide Geografieschlüssel |
| `vehicles` | `report_year, geo_version, municipality_id, vehicle_category_code` | many-to-one zu `population` über Jahr, Gebietsstand, Gemeinde |
| `heating` | `report_year, geo_version, municipality_id` | Zu `population` über dieselben drei Schlüssel; Quelle muss eindeutig sein |
| `building_category` | `report_year, geo_version, municipality_id` | Wie `heating` |
| `years` | `report_year` | Wurzel der AV-Jahresdaten, Vereinigung vorhandener Personal-/Umsatzjahre |
| `staff` | `report_year, education` | many-to-one zu `years` |
| `revenue` | `report_year` | Eindeutig zu `years`; native many-to-one-Deklaration genügt |

SLayer kann die geprüften inversen Beziehungen verwenden. Keine doppelten manuellen Joinpfade in beide Richtungen pflegen. Nie nur über den Gemeindenamen verbinden; nie `geo_version` aus dem kommunalen Join weglassen.

Die kommunalen Faktentabellen erhalten zusätzlich `cell_id VARCHAR`, abgeleitet als `geo_version || '|' || report_year || '|' || municipality_id`, z.B. `2025|2025|2401`. Diese technische Spalte vereinfacht die native Abdeckungsprüfung; sie ersetzt den fachlichen zusammengesetzten Primärschlüssel nicht. Im AV-Bereich genügt `report_year` als Grundzellenschlüssel. Es braucht keine neue Zellentabelle und keine Klasse dafür.

`population` enthält im Pilot nur 2025. Ihre Verwendung als kommunale Wurzel ist deshalb auf dieses freigegebene Datenpaket beschränkt. Eine spätere neue Jahreslieferung muss die entsprechenden Grundzellen enthalten und erneut geprüft werden. Die Anwendung erfindet keine Zeilen für nicht vorhandene Jahre.

### 2.2 Metadaten je Modell

Beispiel für `vehicles`:

```yaml
meta:
  analytics:
    source_id: vehicles
    domain: municipal_annual
    root_model: population
    population: so_municipalities_v2025
    period_kind: year
    cell_key: cell_id
    temporal_kind: stock
    reference_dates:
      "2025": null
    coverage: unknown
```

Verbindliche Bedeutung:

- `source_id` verweist auf das Quellenmanifest. Modelle dürfen mehrere Kennzahlen desselben Fakts enthalten.
- `domain` und `population` sind kleine Vergleichbarkeitscodes. Der kommunale Bestand von 2025 und Steuerdaten mit Geografie 2026 erhalten unterschiedliche Population-Codes. AV-Kantonsdaten bilden einen eigenen Bereich. Keine Ontologie implementieren.
- `root_model` ist pro Bereich explizit und autorengepflegt. Der Compiler muss keine neue optimale Joinwurzel suchen. Alle Quellen einer Analyse brauchen dieselbe freigegebene Wurzel und Population.
- `cell_key` ist eine existierende native Spalte. Sie enthält je Grundzelle denselben nicht leeren Wert. Ihre Zuordnung wird geprüft.
- `period_kind` muss für queryfähige Modelle `year` sein. `period_start` ist der technische Jahresbucket; `reference_dates` beschreibt gesondert den beobachteten Stichtag.
- `coverage=unknown` ist im Pilot die Kategorie-Standardregel. Die Anwendung darf fehlende Kategoriezeilen nicht in 0 umwandeln. Eine `closed_world`-Erweiterung ist ausdrücklich nicht Teil von V1.

Tatsächliche `available_years`, Zeilenanzahlen, geprüfte kleine Kategorienlisten und `complete_values` werden durch die Qualitätsprüfung ermittelt und ins generierte Manifest aufgenommen. Im gelieferten Fahrzeugstand decken die Codes `"01"`, `"30"`, `"43"`, `"60"` und `"90"` alle 106 Grundzellen ab; die Beispielrechnungen konzentrieren sich auf `01` und `60`. Das ist ein Befund über eine primitive Dimension, keine Liste erlaubter Benutzerfragen. Eine falsche manuelle Behauptung darüber darf eine fehlgeschlagene Datenprüfung nicht überschreiben.

### 2.3 Metadaten je Kennzahlspalte

```yaml
name: vehicles
type: INT
label: Einzelne Fahrzeuge
description: Anzahl einzelner immatrikulierter Fahrzeuge gemäss Quelldefinition.
allowed_aggregations: [sum]
meta:
  analytics:
    metric_id: vehicles.count
    unit: vehicles
    temporal_kind: stock
    allowed_aggregations: [sum]
    dimensions: [municipality, district, year, vehicles.category, vehicles.group]
    additive_over: [municipality, district, vehicles.category, vehicles.group]
```

Native Typbezeichner nach dem tatsächlich installierten `DataType`-Enum schreiben; Beispiele nicht ungeprüft als frei erfundene Strings übernehmen. Der geprüfte Enum hat keinen separaten DECIMAL-Wert. Exakte Geldwerte werden deshalb mit `type: DOUBLE` **und** `db_type: DECIMAL(18,2)` modelliert. Mit dieser Kombination blieben SUM und time_shift(SUM) in der realen Probe Python-Decimal und wurden als exakte Dezimalstrings serialisiert; ohne `db_type` wurden sie zu Floats. `label`/`description` sind native Felder. Die projektspezifische Liste `allowed_aggregations` wird trotz nativer Spaltenliste eigenständig auf jedem AggregateNode geprüft, da ein Ausdrucksaggregat sonst Spalten-Gates umgehen kann.

Die öffentliche Kennzahl bezeichnet eine geprüfte Basis-Spalte. Eine fachlich feste Ableitung wie `age_65_plus = age_65_79 + age_80_plus` darf beim Vorbereiten materialisiert werden. Ein Agent liefert keine Rohzeilenformel unter einem Aggregat.

### 2.4 Metadaten je Dimension

```yaml
name: vehicle_category_code
type: TEXT
label: Fahrzeugart
meta:
  analytics:
    dimension_id: vehicles.category
    scope: fact
    owner: vehicles
    value_type: string
    label_column: vehicle_category_name
```

Gemeinsame Dimensionen haben `scope=shared`. Die ID `municipality` bezeichnet einen Integer, `district` ebenfalls den Bezirksschlüssel, `year` einen Integer-Jahreswert. Anzeigenamen werden über `label_column` erschlossen. Der native Pfad zur Dimension wird vom geprüften Modellgraphen und der festen Wurzel abgeleitet. Wenn der Pfad mehrdeutig ist, wird das Modell beim Authoring zurückgewiesen; keine beliebige erste Kante wählen.

Wichtige IDs im Pilot:

| Quelle | Öffentliche Kennzahlen | Zusätzliche faktlokale Dimensionen |
|---|---|---|
| Bevölkerung | `population.count`, `.women`, `.men`, `.swiss`, `.foreign`, `.age_0_19`, `.age_20_39`, `.age_40_64`, `.age_65_79`, `.age_80_plus`, `.age_65_plus` | Keine künstliche Alters-/Geschlechtskreuzdimension; die Werte sind getrennte Spalten |
| Fahrzeuge | `vehicles.count`, `vehicles.registrations` | `vehicles.category`, `vehicles.group` |
| AV-Personal | `staff.count` | `staff.education` |
| AV-Umsatz | `revenue.nominal_chf` | Keine Ausbildungsdimension |
| Heizung | `heating.buildings`, `.heat_pump`, `.heating_oil`, `.gas`, `.wood`, `.electricity`, `.district_heating`, `.other_or_unknown` | Keine gemeinsame Gebäudekategorie-Heizungsdimension |
| Gebäudekategorie | `building_category.single_family`, `.multi_family`, `.residential_secondary_use`, `.partially_residential` | Keine Heizungsdimension |

Der Punktpräfix in verkürzten Tabellenzellen steht für den angegebenen Quellenpräfix, z.B. `.women` für `population.women`. Das wiederholte Gebäudetotal der Kategorienquelle wird zur Qualitätskontrolle verwendet; als öffentliche kanonische Total-Kennzahl genügt `heating.buildings`. Es wird nicht mit dem anderen Total addiert.

## 3 Compilerablauf

`SemanticCompiler.compile(request)` arbeitet ohne Datenbankzugriff:

1. DTO-/Budgetregeln, IDs und Eindeutigkeit prüfen.
2. Alle verwendeten Kennzahlen und Dimensionen auflösen. Gesperrte bekannte Quellen ergeben `E_MODEL_UNAVAILABLE`; unbekannte IDs ihren spezifischen Fehler.
3. Gemeinsame Domain/Wurzel/Population bestimmen. Unvereinbare Bereiche oder Gebietsstände ergeben `E_INCOMPATIBLE_POPULATION`.
4. Sichtbare Jahre prüfen. Für einen direkten Blattwert müssen alle verlangten sichtbaren Jahre in der Quelle vorhanden sein. Ein nicht verfügbares sichtbares Jahr ergibt `E_PERIOD_UNAVAILABLE`. Fehlende Vergleichsjahre sind später ein NULL-Ergebnis mit `MISSING_BASE_PERIOD`. Insbesondere werden fehlende Umsatzjahre 1980–1982 nicht auf 0 gesetzt.
5. Effektives Ausgabegrain und Zeitform festlegen. Eine Jahresserie benutzt native `time_dimensions`. Ein PeriodNode ohne öffentliches `year` ist nur bei genau einem sichtbaren Jahr erlaubt; das Jahr wird intern ergänzt und am Ende entfernt.
6. Alle Bäume post-order prüfen und native AST-Ausdrücke erzeugen. Datenabhängige Blätter, Einheiten, Grain und erforderliche Jahre werden dabei gesammelt.
7. Interne Prüfmeasures strukturell deduplizieren, auf Budget prüfen und hinzufügen. Benötigte Vergleichsjahre erweitern den nativen Scanrahmen.
8. `SlayerQuery` mit fester Wurzel, festem `to_many_handling="error"` und `limit=10001` erzeugen. Native Aliase sind `m0`, `m1`, … und `h0`, `h1`, …; niemals Benutzerstrings als Alias einfügen.
9. Formeln mit `ast.unparse()` serialisieren und nativ mit `parse_expr` prüfen. `SlayerQuery.model_validate` prüft die native Querystruktur.

Der Worker führt anschliessend einen nativen Dry-run, die Warnungsprüfung, die echte Query und die Ergebnisprüfung aus. Eine zusätzliche allgemeine SQL-Analyse oder Traversierung privater nativer Query-DAGs ist nicht erforderlich.

## 4 Grain, Additivität und Rechenoperationen

### 4.1 Aggregationen

Eine Kennzahl darf nur über Dimensionen gruppiert beziehungsweise lokal gefiltert werden, die in ihrer eigenen `dimensions`-Liste stehen. Eine technisch mögliche Verbindung zu einer anderen Tabelle ergänzt keine beobachtete gemeinsame Merkmalsverteilung.

Das effektive Grain eines AggregateNode ist sein explizites `grain` oder das Ausgabegrain. Bei einem explizit gröberen Grain muss jede Dimension im Ausgabegrain enthalten sein. Für einen Bezirksnenner pro Gemeinde wird deshalb beispielsweise nach `["district","municipality"]` gruppiert und der Nenner auf `["district"]` gesetzt. Nur ein echt gröberes Grain benötigt die Nennerrolle; ein gröberer Normaloutput ergibt `E_REFERENCE_ONLY_DENOMINATOR`. Gleiches Grain ist für normale Outputs erlaubt.

Im Jahresserien-/PeriodNode-Modus bleibt `year` in **jedem** Blattgrain, insbesondere in jedem Nenner. Wird das Jahr für einen Einjahresvergleich nur intern ergänzt, ergänzt der Compiler es auch in einem expliziten Nennergrain wie `[]` oder `["municipality"]`. Ist `year` öffentlich ausgegeben, muss ein explizites Grain es enthalten; seine Auslassung wird in V1 abgewiesen. So wird aus einem für 2025 gedachten Bevölkerungsnenner durch den erweiterten Scanrahmen nicht versehentlich die Summe der Bevölkerung 2024 und 2025. Jahresübergreifende Referenzsummen innerhalb dieses Modus sind nicht unterstützt.

Bei einer Summe müssen alle zusammengefassten variierenden Dimensionen als additiv freigegeben sein. Ein exaktes `eq` oder ein `in` mit einem Wert fixiert eine Dimension. Für komplexere Prädikate wird konservativ von Variation ausgegangen; kein Mengen-/SAT-Beweissystem bauen. `min`/`max` benötigen eine ausdrückliche Freigabe der Kennzahl. Die Pilot-Kennzahlen geben zunächst nur `sum` frei; kein freies Mittelwertaggregat anbieten.

Bestände (`stock`) dürfen innerhalb eines Jahres über passende Gemeinden/Kategorien addiert werden. Eine Summe über mehrere Jahre ohne `year` im jeweiligen effektiven **Blattgrain** wird abgewiesen; die Prüfung nur am äusseren Ausgabegrain wäre ungenügend. Jahresflüsse (`flow`), hier nominaler Umsatz, dürfen Jahre addieren, wenn `year` in `additive_over` steht. Eine statische Grösse ohne belegte Jahreszuordnung wird nicht automatisch in eine Zeitreihe übertragen.

### 4.2 Binäre Operationen

- **Add/Subtract:** gleiche normierte Einheit und gleiches Grain. Ergebnis immer `nature=calculated`. Eine Differenz vorhandener Marginalzahlen wird nicht als beobachtete Teilgruppe bezeichnet.
- **Multiply:** genau ein Operand ist unmittelbar eine numerische ConstantNode, der andere datenabhängig. Datenwert × Datenwert ergibt `E_UNSUPPORTED_PRODUCT`. Ausdrücke, die nur Konstanten enthalten, sind kein eigenständiges Analyseoutput.
- **Divide:** Der Nenner ist unmittelbar AggregateNode, ConstantNode oder ein PeriodNode `shift/fixed_year`, dessen direkter Inhalt ein AggregateNode ist. Ein BinaryNode als Nenner ergibt `E_UNSUPPORTED_DENOMINATOR`. Der datenabhängige Nenner hat gleiches Grain oder ausdrücklich gröberes Grain; das Ergebnis übernimmt das feinere zulässige Grain.
- Division wird immer als `scale * numerator / nullif(denominator, 0)` erzeugt. Eine konstante 0 im Nenner wird vor Ausführung abgewiesen. Kein Agentparameter erlaubt, 0 beziehungsweise fehlend durch 1 zu ersetzen.
- Ein `relative_change`-PeriodNode darf intern den engen Ausdruck `current / nullif(previous, 0) - 1` erzeugen, auch wenn sein `value` eine zulässige zusammengesetzte Kennzahl ist. Das ist ein festes Compiler-Template, keine generelle Freigabe beliebiger Ausdrucksnenner.

Jede erzeugte Division registriert ihren Nennercheck, auch diese intern erzeugte Division der relativen Änderung. Abhängigkeiten sämtlicher verschachtelter Blätter, Nenner und Perioden werden bis zum öffentlichen Output vereinigt. Ein vorheriger Wert 0 muss `ZERO_DENOMINATOR` ergeben und darf nicht nur als kommentarloses NULL durchlaufen.

Die einfachen Grenzen sperren insbesondere `women * age65 / population` sowie die Umgehung `women / (population / age65)`. Sie beweisen keine allgemeine Wahrheit natürlichsprachlicher Aussagen. Der Dienst kann die Zahl «Frauen ab 65» aus den vorhandenen Marginalzahlen nicht liefern und soll das erklären.

### 4.3 Einheiten

Eine kleine normalisierte Liste von Basiseinheiten und Exponenten genügt: `(("CHF",1),("persons",-1))`. Division subtrahiert Exponenten, eine Konstante verändert die Einheit nicht, Addition/Subtraktion verlangen Gleichheit. `vehicles` und `registrations` sind unterschiedliche Einheiten; `persons` und `staff_persons` ebenfalls, weil Mitarbeitende nicht mit Gemeindebevölkerung gleichgesetzt werden sollen. Keine Bibliothek für allgemeine physikalische Einheiten einführen.

## 5 Sichere Erzeugung nativer Formeln

Verwende die Python-Standardbibliothek `ast`. Werte werden `ast.Constant`, Mengen `ast.Tuple` und Prädikate feste `ast.Compare`-/`ast.BoolOp`-Formen. Referenzen stammen ausschliesslich aus dem Katalog.

```python
def native_ref(parts: tuple[str, ...]) -> ast.expr:
    node = ast.Name(id=parts[0], ctx=ast.Load())
    for part in parts[1:]:
        node = ast.Attribute(value=node, attr=part, ctx=ast.Load())
    return node

def render(node: ast.expr) -> str:
    formula = ast.unparse(ast.fix_missing_locations(node))
    parse_expr(formula)
    return formula
```

Beim Laden native Namensbestandteile mit `isidentifier()`, `keyword.iskeyword()` und nativer Auflösung prüfen. Bestehende rohe Sonderzeichen-Spalten werden im Authoring kanonisch benannt. Kein `eval`, kein Zusammenfügen eines Request-Werts als DSL-Text, kein SQL-Escaping als Ersatz für Python-Literal-Escaping. Die native Funktion `canonical_measure_text()` dient nicht als sicherer Serializer; sie wurde dafür nicht entworfen. Öffentliche `query_variables` gibt es nicht.

Lokale Filter werden in die Aggregatargumente aufgenommen:

```text
sum(iif(vehicles.vehicle_category_code in ('01', '60'), vehicles.vehicles, None))
```

`None` ist wesentlich: Eine fehlende Beobachtung wird nicht in eine beobachtete 0 verwandelt. Globale Fahrzeugartenfilter werden abgewiesen, damit der native Joinfilter nicht die Bevölkerungsgrundgesamtheit per EXISTS verkleinert. Globale Raumfilter gelten für alle Blätter und jeden Nenner identisch.

## 6 Zeitregeln und native Templates

### 6.1 Berichtsjahr und Beobachtungsstichtag

`period_start=2025-01-01` bezeichnet den technischen Jahresbucket. Bevölkerung und GWS haben einen belegten Stichtag 31.12.2025. Der Fahrzeugstichtag bleibt unbekannt. Gleiche Berichtsjahre sind im Standardmodus kombinierbar, aber die Quelle mit unbekanntem Stichtag erzeugt `SAME_REPORTING_YEAR_REFERENCE_DATE_UNKNOWN`. Bekannte unterschiedliche Stichtage erzeugen einen entsprechenden erklärenden Hinweis.

Bei `require_same_reference_date=true` müssen die miteinander kombinierten Bestandsquellen innerhalb jeder beabsichtigten Jahresgruppe bekannte gleiche Stichtage haben: sonst `E_REFERENCE_DATE_UNKNOWN` beziehungsweise `E_REFERENCE_DATE_MISMATCH`. Ein absichtlicher Vorjahresvergleich darf verschiedene Jahre vergleichen. Ein Jahresfluss besitzt keinen einzelnen Bestandsstichtag; die Antwort bezeichnet das Verhältnis Fluss/Bestand entsprechend. Der Schalter macht aus einem Fluss keinen Stichtagswert.

### 6.2 Vorjahresvergleich: Scanrahmen erweitern

Bei sichtbarem 2025 und `years=1` lautet der native Zeitraum 2024-01-01 bis 2025-12-31. Der Compiler benutzt die kleinste zusammenhängende Jahresspanne, welche alle sichtbaren und benötigten Vergleichsjahre einschliesst. Die gesamte eingelesene Spanne unterliegt den Jahresbudgets. Es darf keinen zusätzlichen globalen Filter `report_year == 2025` geben.

```python
SlayerQuery(
    source_model="years",
    time_dimensions=[{
        "dimension": "period_start", "granularity": "year",
        "date_range": ["2024-01-01", "2025-12-31"],
    }],
    measures=[{
        "name": "m0",
        "formula": "(sum(revenue.nominal_chf) / nullif(sum(staff.staff), 0)) / nullif(time_shift(sum(revenue.nominal_chf) / nullif(sum(staff.staff), 0), -1, 'year'), 0) - 1",
    }],
    to_many_handling="error", limit=10001,
)
```

Die explizite Erweiterung ist durch eine konkrete native Probe begründet: Ein zusammengesetztes Cross-Fact-Verhältnis konnte bei auf 2025 begrenztem nativen Rahmen ein NULL-Vorjahr liefern. Mit erweitertem Rahmen wurde das richtige Vorjahr berechnet. Nicht pauschal annehmen, dass native Zeitfunktionen bei jeder Ausdrucksform selbständig frühere Daten nachladen.

`shift`: `time_shift(value, -years, 'year')`. `absolute_change`: `value - shifted_value`. `relative_change`: `value / nullif(shifted_value,0) - 1`. `fixed_year` ist nur bei einem sichtbaren Jahr erlaubt und wird über die entsprechende Verschiebung auf dieses Basisjahr umgesetzt. Ein fixer Basisnenner für mehrere sichtbare Jahre ist `E_UNSUPPORTED_FIXED_BASE_SERIES`.

Für eine Verschiebung müssen auch die internen Coverage- und Nenner-Prüfausdrücke verschoben werden. Veränderungsberechnungen benötigen die Prüfungen der aktuellen **und** der Vergleichsperiode. Die aktuelle Vollständigkeit beweist nicht die Vollständigkeit des Vorjahres. ASTs der Prüfausdrücke behalten; keine bereits gerenderten Aliasstrings rückwärts parsen.

### 6.3 Durchschnitt von Jahrestotalen

```text
avg(sum(staff.staff, partition_by=report_year))
count(sum(staff.staff, partition_by=report_year))
```

Das innere `partition_by` enthält sämtliche effektiven Blatt-Gruppierungsschlüssel sowie `report_year`, auch eine zulässige faktlokale Dimension wie `staff.education`. Die äussere Query hat dabei **keine** native TimeDimension. Sie begrenzt die Jahre über normale geprüfte Jahresfilter. Das innere `report_year` ist die physische Integer-Spalte; `year(period_start)` ohne passende TimeDimension führte in der Probe zu einem `PartitionKeyError`.

Der interne Count muss der verlangten Anzahl Jahre entsprechen. Native `avg` ignoriert fehlende Jahre; der Dienst darf daraus keinen vollständigen Periodenmittelwert machen. Fehlende Jahresabdeckung setzt den betroffenen Output auf NULL mit `MISSING_YEAR_COVERAGE`. Numerische 0 zählt als vorhandener Jahreswert.

`mean_annual_totals` verlangt `op=sum`; `year` darf nicht ausgegeben werden. Es darf weder unter einem PeriodNode liegen noch in derselben Query mit irgendeinem PeriodNode gemischt werden, weil beide unterschiedliche native äussere Zeitebenen benötigen. Mehrere kompatible Jahresmittel und direkte erlaubte Jahresfluss-Summen dürfen denselben aggregierten Zeitraum verwenden.

## 7 Quellenabdeckung, NULL und beobachtete Teilmengen

Es wird kein allgemeiner Abdeckungsplaner gebaut. Folgende gezielte native Hilfswerte genügen:

| Prüfung | Native Hilfswerte | Konsequenz |
|---|---|---|
| Grundzellen einer Quelle | `count_distinct(fact.cell_id, partition_by=shared_grain)` gegen entsprechenden Count der Wurzel | Bei fehlender Grundzelle betroffene Outputs NULL und `MISSING_SOURCE_COVERAGE` |
| AV-Grundzellen | Dasselbe mit `fact.report_year` und `years.report_year` | Wie oben |
| Vollständiger Jahresmittelwert | `count(inner_annual_sum)` | Bei abweichender Jahresanzahl NULL und `MISSING_YEAR_COVERAGE` |
| Divisionsnenner | Derselbe native Nenner als verstecktes Measure | 0: `ZERO_DENOMINATOR`; NULL: `MISSING_DENOMINATOR` |
| Vergleichsbasis | Verschobene Basiswerte und verschobene Prüfungen | Fehlend: `MISSING_BASE_PERIOD`; fehlerhafte Basisabdeckung bleibt erkennbar |

Diese Counts stehen **vor** lokalen Kategoriebedingungen. Bei Ausgabe von Gemeinde, Jahr und Fahrzeugart wird beispielsweise explizit auf `[municipality_id, year(period_start)]` partitioniert. Die zusätzliche Fahrzeugart darf den Wurzelcount nicht ändern. Bei einem gröberen Nenner bezieht sich sein Abdeckungscheck auf dessen Grain, nicht blind auf die feinere Ausgabezeile.

`count_distinct`-Prüfausdrücke werden pro Quelle, Grain, Zeitverschiebung und globalem Filterkontext dedupliziert. Keine Nachabfrage pro Ergebniszeile. Die Pilot-Pflichtkennzahlen enthalten keine zugelassenen NULL-Rohwerte: Das Authoring weist solche Nullwerte zurück. Daher muss V1 keinen zusätzlichen allgemeinen nullable-Metric-Planer entwickeln.

Die Grundzellenprüfung und die Kategorieabdeckung beantworten unterschiedliche Fragen. Bei Fahrzeugen sind 106 Gemeinden vorhanden, aber keine vollständige 106×42-Matrix. Für nachgewiesen vollständige Codes wie `01` und `60` kann eine über Gemeinden aggregierte Kategorieauswahl als vollständig gelten. Für Kategorien, die nicht als vollständig belegt sind, darf die Summe vorhandener Beobachtungen ausgegeben werden, aber mit `COVERAGE_UNKNOWN` und der Beschreibung «Summe vorhandener Beobachtungen». Ein fehlender Einzelwert bleibt NULL. Es werden keine künstlichen Kategoriezeilen erzeugt. Für die unverändert publizierte Gesamtsumme aller Fahrzeugzeilen wird die Kennzahl als publizierter Bestand mit dokumentierter Kategorie-Abdeckungsgrenze beschrieben; die Anwendung behauptet keine Vollständigkeit einer nicht gelieferten Kreuztabelle.

In V1 gibt es keine Anfrageoption, welche belegte fehlende Grundzellen als vollständige Summe akzeptiert. Nur unabhängige andere Outputs bleiben nutzbar. `finalize` verfolgt deshalb je Output die Abhängigkeit von Prüfungen und setzt nur betroffene Zellen auf NULL.

Bleibt ein nativer Wert NULL, obwohl kein spezifischer Check fehlgeschlagen ist, bekommt er `NO_MATCHING_OBSERVATIONS`. Das betrifft beispielsweise eine lokale Kategorieauswahl ohne Treffer bei ansonsten vollständiger Quelle. Spezifische vorhandene Ursachen werden vor diesem Fallback verwendet. Eine 0 im Vorjahresnenner ist nicht eine fehlende Vorjahresperiode; eine fehlgeschlagene innere Division wird mit ihrem eigentlichen Grund weitergegeben.

## 8 Native Prüfung und Finalisierung

`check_native_response` prüft die erwartete Population/Wurzelzuordnung, erwartete Spalten und strukturierte Warnungskategorien. Für die erzeugten Templates wird keine native Broadcast-, Association-, Unrelated- oder SemiJoin-Warnung erwartet. Solche und unbekannte Warnungskategorien ergeben `E_NATIVE_PLAN_UNSUPPORTED`; kein Matching von englischen Warnungstexten. Eine konkrete künftig notwendige Kategorie darf nur mit einem passenden Integrationstest freigegeben werden. `warnings=[]` allein ersetzt die eigenen vorherigen Fachprüfungen nicht.

`finalize` verarbeitet in dieser Reihenfolge:

1. Vollständigkeit innerhalb der nativen 10’000-Zeilen-Grenze und der erwarteten Spalten prüfen.
2. Aus dem vollständig berechneten Resultat nur sichtbare Jahre auswählen.
3. Zugeordnete Prüfungen auswerten und betroffene Zellen als NULL mit Status ausgeben.
4. Native Aliase auf öffentliche IDs abbilden; Jahresbucket auf Integer-Jahr abbilden; Hilfsjahr gegebenenfalls entfernen.
5. Hilfsspalten entfernen, kanonische Output-Metadaten, Quellen und Zeitangaben ergänzen.
6. Deterministisch sortieren, öffentliches Limit anwenden und `truncated` korrekt setzen.
7. Zahlen-/Dezimal-/Datumsdarstellung und Gesamtgrösse prüfen.

Ein unerwartetes nicht endliches natives Ergebnis wird mit `E_ENGINE_FAILURE` und dem sicheren Detailcode `NON_FINITE_RESULT` zurückgewiesen. Es wird weder als ungültiges JSON serialisiert noch still zu 0 gemacht.

Python darf in diesem Schritt **keine** Kennzahl neu berechnen, Daten gruppieren, Fakten verknüpfen, fehlende Jahre interpolieren oder SLayer durch handgeschriebenes SQL ersetzen. Auch ein Fehler in einem nativen Template wird durch ein korrigiertes Template und einen Integrationstest behoben.

## 9 Erweiterung einer Quelle ohne neue Architektur

Ein Autor ergänzt eine geprüfte physische Tabelle, ihre SLayer-YAML-Definition und `meta.analytics`, danach einen unabhängigen Sollfall sowie einen relevanten negativen Fall. `author verify` prüft Schlüssel, Beziehungen, Typen, Kategorien und Zeit-/Raumangaben. Nach erfolgreichem Neubau kann ein neuer Bundle-Stand geladen werden. Eine zusätzliche Quelle mit bereits unterstützten Dimensionen und Zeitformen verlangt keine neue Serviceklasse und keine neue MCP-Methode.

Ein Ausbau auf Monatsbestände, neue Gebietsbrücken, Schätzungen oder beliebige native Query-DAGs verändert dagegen den Fachvertrag und benötigt eine gesonderte Spezifikationsänderung.

## Quellen und technische Nachweise

- [SLayer Queries](https://docs.motley.ai/slayer/concepts/queries/) und [Formeln](https://docs.motley.ai/slayer/concepts/formulas/).
- [Geprüfter SLayer-Quellstand](https://github.com/MotleyAI/slayer/tree/516539dfec2979180695efa4351e0adccd6b2816): `slayer/core/query.py`, `slayer/core/models.py`, `slayer/engine/query_engine.py`, `slayer/engine/syntax/`.
- `evidence/native_real/`: reale native Modell-/Queryproben gegen unabhängige Rohdaten-Sollwerte.
- `evidence/semantics/`: Zeitfenster-, Jahresmittel-, Literal- und Quellenabdeckungsproben. Forschungsproben belegen die nativen Bausteine; die Anwendung und ihre vollständige Guard-Verknüpfung bleiben zu implementieren.
