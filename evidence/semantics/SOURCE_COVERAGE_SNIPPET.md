# Geprüfte native Quellenabdeckung

SLayer1.4.1, gleicher Commit wie SEMANTICS_DESIGN.md. Vollständiges Fixture und SQL im benachbarten source_coverage_probe.py / source_coverage_probe_results.json.

## Unabhängig vom lokalen Kategorieprädikat

```python
SlayerQuery(
    source_model="cells",
    dimensions=["municipality"],
    filters=["report_year >= 2024", "report_year <= 2025"],
    measures=[
        {"name": "filtered_value", "formula": "sum(iif(staff.education == 'absent_category', staff.stock, None))"},
        {"name": "source_cells", "formula": "count_distinct(staff.cell_id, partition_by=municipality)"},
        {"name": "expected_cells", "formula": "count_distinct(id, partition_by=municipality)"},
    ],
    to_many_handling="error",
)
```

| Gemeinde | filtered_value | source_cells | expected_cells |
|---|---:|---:|---:|
| A | NULL |2|2|
| B | NULL |1|2|

Der lokale Filter liefert nirgends einen Wert. Die Quellenabdeckung wird trotzdem korrekt vor diesem Filter gezählt.

## Mit Kategorie im Ausgabegrain

Bei dimensions=[municipality, vehicles.kind] und nativer time_dimension period_start/year wird das gemeinsame Hilfsgrain explizit als `[municipality, year(period_start)]` bezeichnet:

```text
count_distinct(vehicles.cell_id, partition_by=[municipality, year(period_start)])
count_distinct(population.cell_id, partition_by=[municipality, year(period_start)])
count_distinct(staff.cell_id, partition_by=[municipality, year(period_start)])
count_distinct(id, partition_by=[municipality, year(period_start)])
```

Neben diesen Counts läuft die echte bedingte Quote

```text
1000 * sum(iif(vehicles.kind == 'car', vehicles.n, None))
     / nullif(sum(population.n, partition_by=[municipality, year(period_start)]), 0)
```

Fahrzeug- und Bevölkerungsabdeckung beträgt überall1/expected1, auch in den Motorrad-Ausgabezeilen, deren bedingter Autozähler NULL ist. Staff fehlt in B2024 vollständig: staff_cells0/expected1 für beide Arten. Die Counts werden im Test bewusst zusammen gezeigt; der produktive Compiler erzeugt nur Counts tatsächlich verwendeter Quellen.

Beide Abfragen laufen nativ mit `to_many_handling="error"`, **ohne Warnungen**. Es entsteht keine Kategorie-0-Synthese. Das abweichende source_cells/expected_cells-Paar ist das Signal für fehlende Grundzellen, keine Behauptung über vollständige Kategorien innerhalb einer vorhandenen Zelle.
