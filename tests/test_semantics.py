"""N01–N17, M02–M09 and compiler/result budgets.

Mutation fixtures are explicitly derived DB copies. They are never accepted as
an unchanged production snapshot and never replace the frozen positive cases.
"""

from __future__ import annotations

from dataclasses import replace

import duckdb
import pytest

from test_real_queries import aggregate, binary, request, ratio, selected_vehicles


def period(value, op="relative_change", **kwargs):
    return {
        "kind": "period",
        "op": op,
        "value": value,
        **({"years": 1} if op != "fixed_year" else {}),
        **kwargs,
    }


def compile_request(catalog, payload):
    from slayer_app.contracts import AnalysisRequest
    from slayer_app.semantics import SemanticCompiler

    return SemanticCompiler(catalog).compile(AnalysisRequest.model_validate(payload))


REJECTIONS = [
    (
        "N01",
        request({"people": aggregate("population_sex_nationality.count")}),
        {"E_MODEL_UNAVAILABLE"},
    ),
    (
        "N02",
        request(
            {"ratio": ratio()},
            period={
                "from_year": 2025,
                "to_year": 2025,
                "require_same_reference_date": True,
            },
        ),
        {"E_REFERENCE_DATE_UNKNOWN"},
    ),
    (
        "N03",
        request(
            {"people": aggregate("population.count")},
            filters=[{"field": "vehicles.category", "op": "eq", "values": ["01"]}],
        ),
        {"E_GLOBAL_FILTER_NOT_SHARED"},
    ),
    (
        "N04",
        request(
            {"revenue": aggregate("revenue.nominal_chf")}, group_by=["staff.education"]
        ),
        {"E_CROSS_CLASSIFICATION_UNAVAILABLE", "E_GRAIN_MISMATCH"},
    ),
    (
        "N05",
        request({"staff": aggregate("staff.count")}, start=2024),
        {"E_TIME_AGGREGATION_NOT_ALLOWED"},
    ),
    (
        "N06_product",
        request(
            {
                "made_up": binary(
                    "multiply",
                    aggregate("population.women"),
                    aggregate("population.age_65_plus"),
                )
            }
        ),
        {"E_UNSUPPORTED_PRODUCT"},
    ),
    (
        "N06_nested_denominator",
        request(
            {
                "made_up": binary(
                    "divide",
                    aggregate("population.women"),
                    binary(
                        "divide",
                        aggregate("population.count"),
                        aggregate("population.age_65_plus"),
                    ),
                )
            }
        ),
        {"E_UNSUPPORTED_DENOMINATOR"},
    ),
    (
        "N07_women_age",
        request({"made_up": aggregate("population.women_65_plus")}),
        {"E_UNKNOWN_METRIC"},
    ),
    (
        "N07_building_heating",
        request(
            {"made_up": aggregate("heating.heat_pump")},
            group_by=["building_category.category"],
        ),
        {"E_UNKNOWN_DIMENSION", "E_CROSS_CLASSIFICATION_UNAVAILABLE"},
    ),
    (
        "N09",
        request(
            {
                "made_up": binary(
                    "add", aggregate("population.count"), aggregate("vehicles.count")
                )
            }
        ),
        {"E_UNIT_MISMATCH"},
    ),
    (
        "N10",
        request(
            {"people": aggregate("population.count", grain=[])},
            group_by=["municipality"],
        ),
        {"E_REFERENCE_ONLY_DENOMINATOR"},
    ),
    (
        "N12",
        request(
            {
                "ratio": binary(
                    "divide",
                    aggregate("staff.count"),
                    aggregate("staff.count", grain=[]),
                )
            },
            group_by=["year"],
            start=2024,
        ),
        {"E_GRAIN_MISMATCH", "E_TIME_AGGREGATION_NOT_ALLOWED"},
    ),
    (
        "N13",
        request(
            {
                "mean": aggregate("staff.count", temporal_reduce="mean_annual_totals"),
                "shift": period(aggregate("revenue.nominal_chf"), "shift"),
            }
        ),
        {"E_UNSUPPORTED_TEMPORAL_COMPOSITION"},
    ),
    (
        "N14",
        request(
            {"base": period(aggregate("revenue.nominal_chf"), "fixed_year", year=2023)},
            group_by=["year"],
            start=2024,
        ),
        {"E_UNSUPPORTED_FIXED_BASE_SERIES"},
    ),
    (
        "N15",
        request(
            {"revenue": aggregate("revenue.nominal_chf")},
            group_by=["year"],
            start=1980,
            end=1982,
        ),
        {"E_PERIOD_UNAVAILABLE"},
    ),
    (
        "N16",
        request(
            {
                "ratio": binary(
                    "divide",
                    aggregate("taxes.total_chf"),
                    aggregate("population.count"),
                )
            }
        ),
        {"E_MODEL_UNAVAILABLE"},
    ),
    (
        "N17",
        request({"dossiers": aggregate("ebau.submitted_dossiers")}),
        {"E_MODEL_UNAVAILABLE"},
    ),
]


@pytest.mark.parametrize(
    "case,payload,codes", REJECTIONS, ids=[case[0] for case in REJECTIONS]
)
def test_semantic_rejection_before_native_execution(catalog, case, payload, codes):
    from slayer_app.contracts import AnalysisError

    with pytest.raises(AnalysisError) as raised:
        compile_request(catalog, payload)
    assert raised.value.code in codes
    if case == "N01":
        assert raised.value.details.get("quality_code") == "DUPLICATE_KEY"


def test_N08_output_id_cannot_assert_an_unobserved_cross_classification(execute):
    expr = binary(
        "subtract", aggregate("population.women"), aggregate("population.age_65_plus")
    )
    data = execute(request({"frauen_65_plus": expr}))
    assert data["rows"] == [{"frauen_65_plus": 82863}]
    metadata = data["outputs"][0]
    assert metadata["nature"] == "calculated"
    assert metadata["label"] != "frauen_65_plus"
    assert "women" in metadata["canonical_expression"]
    assert "age_65_plus" in metadata["canonical_expression"]


def test_N11_hidden_year_is_retained_in_explicit_coarse_denominator(execute):
    from conftest import REAL

    value = binary(
        "divide", aggregate("staff.count"), aggregate("staff.count", grain=[])
    )
    data = execute(request({"growth": period(value)}, group_by=["staff.education"]))
    with duckdb.connect() as connection:
        expected = connection.execute(
            """WITH annual AS (
            SELECT jahr, ausbildung, SUM(anzahl_mitarbeitende) AS n
            FROM read_parquet(?) WHERE jahr IN (2024,2025) GROUP BY jahr,ausbildung),
            totals AS (SELECT jahr,SUM(n) AS n FROM annual GROUP BY jahr)
            SELECT current.ausbildung,(current.n/current_total.n)/(previous.n/previous_total.n)-1
            FROM annual current JOIN annual previous ON current.ausbildung=previous.ausbildung AND previous.jahr=current.jahr-1
            JOIN totals current_total ON current.jahr=current_total.jahr
            JOIN totals previous_total ON previous.jahr=previous_total.jahr
            WHERE current.jahr=2025 ORDER BY current.ausbildung""",
            [str(REAL / "raw" / "staff.parquet")],
        ).fetchall()
    assert len(data["rows"]) == 5
    for got, (education, growth) in zip(data["rows"], expected):
        assert got["staff.education"] == education
        assert got["growth"] == pytest.approx(growth, rel=0, abs=1e-9)


def test_N16_isolated_geography_compatibility(catalog):
    from slayer_app.contracts import AnalysisError

    # Isolate the normative compatibility gate behind normal availability.
    # This derived metadata is never registered in an executable storage.
    model = catalog.models["population"].model_copy(deep=True)
    model.name = "test_tax_geography"
    model.meta["analytics"]["population"] = "so_municipalities_v2026"
    metric = dict(catalog.metrics["population.count"])
    metric["model_id"] = "test_tax_geography"
    models = dict(catalog.models, test_tax_geography=model)
    metrics = dict(catalog.metrics)
    metrics["test.tax_geography"] = metric
    quality = dict(catalog.quality)
    quality["source_status"] = dict(quality["source_status"])
    quality["source_status"]["test_tax_geography"] = dict(
        quality["source_status"]["population"]
    )
    changed = replace(catalog, models=models, metrics=metrics, quality=quality)
    with pytest.raises(AnalysisError) as raised:
        compile_request(
            changed,
            request(
                {
                    "ratio": binary(
                        "divide",
                        aggregate("test.tax_geography"),
                        aggregate("population.count"),
                    )
                }
            ),
        )
    assert raised.value.code == "E_INCOMPATIBLE_POPULATION"


def test_N17_isolated_non_annual_period_gate(catalog):
    from slayer_app.contracts import AnalysisError

    model = catalog.models["population"].model_copy(deep=True)
    model.meta["analytics"]["period_kind"] = "month"
    changed = replace(catalog, models=dict(catalog.models, population=model))
    with pytest.raises(AnalysisError) as raised:
        compile_request(changed, request({"monthly": aggregate("population.count")}))
    assert raised.value.code == "E_UNSUPPORTED_PERIOD"


def codes_for(data, output, **key):
    return {
        cell["code"]
        for cell in data["cell_status"]
        if cell["output"] == output and cell["row_key"] == key
    }


def test_M02_real_derived_zero_population_denominator(execute, derived_catalog):
    from conftest import REAL

    columns = {
        "people": "Total",
        "women": "Total_Weiblich",
        "men": "Total_Maennlich",
        "swiss_people": "Total_SchweizerInnen",
        "foreign_people": "Total_AuslaenderInnen",
        "age_0_19": "Alter_0_bis_19",
        "age_20_39": "Alter_20_bis_39",
        "age_40_64": "Alter_40_bis_64",
        "age_65_79": "Alter_65_bis_79",
        "age_80_plus": "Alter_80_und_mehr",
    }
    assignments = ",".join(
        f"{column}=raw.{source}" for column, source in columns.items()
    )
    with duckdb.connect(str(derived_catalog.database_path)) as connection:
        connection.execute(
            f"UPDATE population SET {assignments},age_65_plus=raw.Alter_65_bis_79+raw.Alter_80_und_mehr FROM read_parquet(?) raw WHERE population.municipality_id=raw.BFS_Nr",
            [str(REAL / "edgecases" / "zero_population_denominator.parquet")],
        ).fetchall()
    data = execute(
        request({"ratio": ratio()}, group_by=["municipality"]), snapshot=derived_catalog
    )
    egerkingen = next(row for row in data["rows"] if row["municipality"] == 2401)
    assert egerkingen["ratio"] is None
    assert "ZERO_DENOMINATOR" in codes_for(data, "ratio", municipality=2401)
    assert all(
        row["ratio"] is not None for row in data["rows"] if row["municipality"] != 2401
    )


def test_M03_missing_real_vehicle_municipality_is_not_zero(execute, derived_catalog):
    from conftest import REAL

    with duckdb.connect(str(derived_catalog.database_path)) as connection:
        remaining = connection.execute(
            "SELECT DISTINCT GDENR FROM read_parquet(?)",
            [str(REAL / "edgecases" / "missing_vehicle_municipality.parquet")],
        ).fetchall()
        assert 2401 not in {row[0] for row in remaining}
        connection.execute("DELETE FROM vehicles WHERE municipality_id=2401").fetchall()
        assert connection.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0] == 2597
    outputs = {
        "vehicles": aggregate("vehicles.count"),
        "people": aggregate("population.count"),
        "ratio": ratio(),
    }
    municipal = execute(
        request(outputs, group_by=["municipality"]), snapshot=derived_catalog
    )
    row = next(row for row in municipal["rows"] if row["municipality"] == 2401)
    assert row == {
        "municipality": 2401,
        "vehicles": None,
        "people": 4362,
        "ratio": None,
    }
    assert "MISSING_SOURCE_COVERAGE" in codes_for(municipal, "ratio", municipality=2401)
    canton = execute(request(outputs), snapshot=derived_catalog)
    assert canton["rows"] == [{"vehicles": None, "people": 293081, "ratio": None}]
    assert "MISSING_SOURCE_COVERAGE" in codes_for(canton, "vehicles")


def test_M04_missing_comparison_year_preserves_current_independent_value(
    execute, derived_catalog
):
    with duckdb.connect(str(derived_catalog.database_path)) as connection:
        for table in ("years", "staff", "revenue"):
            connection.execute(f"DELETE FROM {table} WHERE report_year=2024").fetchall()
    data = execute(
        request(
            {
                "current": aggregate("revenue.nominal_chf"),
                "growth": period(aggregate("revenue.nominal_chf")),
            }
        ),
        snapshot=derived_catalog,
    )
    assert data["rows"] == [{"current": "2762610.00", "growth": None}]
    assert "MISSING_BASE_PERIOD" in codes_for(data, "growth")
    assert not codes_for(data, "current")


def test_M05_incomplete_native_annual_mean_is_null(execute, derived_catalog):
    with duckdb.connect(str(derived_catalog.database_path)) as connection:
        connection.execute("DELETE FROM staff WHERE report_year=2024").fetchall()
    data = execute(
        request(
            {"mean": aggregate("staff.count", temporal_reduce="mean_annual_totals")},
            start=2024,
        ),
        snapshot=derived_catalog,
    )
    assert data["rows"] == [{"mean": None}]
    assert "MISSING_YEAR_COVERAGE" in codes_for(data, "mean")


def test_M06_zero_base_period_relative_division_is_reported(execute, derived_catalog):
    with duckdb.connect(str(derived_catalog.database_path)) as connection:
        connection.execute(
            "UPDATE revenue SET nominal_chf=0 WHERE report_year=2024"
        ).fetchall()
    data = execute(
        request({"growth": period(aggregate("revenue.nominal_chf"))}),
        snapshot=derived_catalog,
    )
    assert data["rows"] == [{"growth": None}]
    assert "ZERO_DENOMINATOR" in codes_for(data, "growth")
    assert "MISSING_BASE_PERIOD" not in codes_for(data, "growth")


def test_M07_shifted_fact_coverage_is_checked(execute, derived_catalog):
    with duckdb.connect(str(derived_catalog.database_path)) as connection:
        connection.execute("DELETE FROM staff WHERE report_year=2024").fetchall()
    value = binary("divide", aggregate("revenue.nominal_chf"), aggregate("staff.count"))
    data = execute(
        request({"growth": period(value), "revenue": aggregate("revenue.nominal_chf")}),
        snapshot=derived_catalog,
    )
    assert data["rows"] == [{"growth": None, "revenue": "2762610.00"}]
    assert {"MISSING_SOURCE_COVERAGE", "MISSING_BASE_PERIOD"} & codes_for(
        data, "growth"
    )
    assert not codes_for(data, "revenue")


def test_M08_absent_local_category_never_becomes_zero(execute):
    data = execute(request({"vehicles": selected_vehicles(["absent_category"])}))
    assert data["rows"] == [] or data["rows"] == [{"vehicles": None}]
    if data["rows"]:
        assert "NO_MATCHING_OBSERVATIONS" in codes_for(data, "vehicles")


@pytest.mark.parametrize(
    "literal", ["O'Brien", "a\\b", "x') or True or ('", "__slayer_ OVER("]
)
def test_M09_filter_values_stay_one_literal(execute, derived_catalog, literal):
    with duckdb.connect(str(derived_catalog.database_path)) as connection:
        connection.execute(
            "UPDATE staff SET education=? WHERE education='Geomatiker'", [literal]
        ).fetchall()
    expr = aggregate(
        "staff.count",
        where=[{"field": "staff.education", "op": "eq", "values": [literal]}],
    )
    data = execute(request({"staff": expr}), snapshot=derived_catalog)
    assert data["rows"] == [{"staff": 25}]


def test_B10_complete_native_rows_before_public_limit(execute, derived_catalog):
    from slayer_app.contracts import AnalysisError

    with duckdb.connect(str(derived_catalog.database_path)) as connection:
        connection.execute(
            "CREATE TEMP TABLE population_seed AS SELECT * FROM population LIMIT 1"
        ).fetchall()
        connection.execute(
            "CREATE TEMP TABLE municipality_seed AS SELECT * FROM municipalities LIMIT 1"
        ).fetchall()
        connection.execute("DELETE FROM population").fetchall()
        connection.execute("DELETE FROM municipalities").fetchall()
        connection.execute(
            "INSERT INTO population SELECT population_seed.* REPLACE ((30000+i)::INTEGER AS municipality_id,concat('2025|2025|',30000+i) AS cell_id) FROM population_seed,range(10000) t(i)"
        ).fetchall()
        connection.execute(
            "INSERT INTO municipalities SELECT municipality_seed.* REPLACE ((30000+i)::INTEGER AS municipality_id) FROM municipality_seed,range(10000) t(i)"
        ).fetchall()
    payload = request(
        {"people": aggregate("population.count")}, group_by=["municipality"], limit=7
    )
    data = execute(payload, snapshot=derived_catalog)
    assert data["matched_rows"] == 10000
    assert data["truncated"] is True
    assert len(data["rows"]) == 7
    assert [row["municipality"] for row in data["rows"]] == list(range(30000, 30007))
    with duckdb.connect(str(derived_catalog.database_path)) as connection:
        connection.execute(
            "INSERT INTO population SELECT * REPLACE (40000::INTEGER AS municipality_id,'2025|2025|40000' AS cell_id) FROM population LIMIT 1"
        ).fetchall()
        connection.execute(
            "INSERT INTO municipalities SELECT * REPLACE (40000::INTEGER AS municipality_id) FROM municipalities LIMIT 1"
        ).fetchall()
    with pytest.raises(AnalysisError) as raised:
        execute(payload, snapshot=derived_catalog)
    assert raised.value.code == "E_RESULT_TOO_LARGE"


def five_nodes():
    return binary(
        "add",
        aggregate("population.count"),
        binary(
            "subtract", aggregate("population.count"), aggregate("population.count")
        ),
    )


def test_B11_40_nodes_accepted_41_rejected_before_engine(catalog):
    from slayer_app.contracts import AnalysisError

    outputs = {f"o{i}": five_nodes() for i in range(8)}
    compiled = compile_request(catalog, request(outputs))
    assert compiled.native_query.limit == 10001
    outputs["o0"] = period(five_nodes(), "shift")
    with pytest.raises(AnalysisError) as raised:
        compile_request(catalog, request(outputs))
    assert raised.value.code == "E_QUERY_TOO_COMPLEX"


@pytest.mark.parametrize(
    "case", ["depth", "outputs", "predicates", "groups", "in_values", "string_length"]
)
def test_B11_other_query_budgets_rejected_before_engine(catalog, case):
    from slayer_app.contracts import AnalysisError

    payload = request({"people": aggregate("population.count")})
    if case == "depth":
        expression = aggregate("population.count")
        for _ in range(7):
            expression = binary(
                "multiply", {"kind": "constant", "value": 1}, expression
            )
        compile_request(catalog, request({"boundary": expression}))
        expression = binary("multiply", {"kind": "constant", "value": 1}, expression)
        payload["outputs"][0]["expr"] = expression
    elif case == "outputs":
        payload = request({f"o{i}": aggregate("population.count") for i in range(9)})
    elif case == "predicates":
        payload = request(
            {
                "vehicles": aggregate(
                    "vehicles.count",
                    where=[{"field": "vehicles.category", "op": "eq", "values": ["01"]}]
                    * 17,
                )
            }
        )
    elif case == "groups":
        payload["group_by"] = [f"test{i}" for i in range(7)]
    elif case == "in_values":
        payload = request(
            {"vehicles": selected_vehicles([f"code{i}" for i in range(101)])}
        )
    else:
        payload = request({"vehicles": selected_vehicles(["x" * 257])})
    with pytest.raises(AnalysisError) as raised:
        compile_request(catalog, payload)
    assert raised.value.code in {"E_QUERY_TOO_COMPLEX", "E_INVALID_REQUEST"}


def test_scalar_unknown_shared_filter_is_empty_with_typed_columns(execute):
    data = execute(
        request(
            {"ratio": ratio()},
            filters=[{"field": "municipality", "op": "eq", "values": [999999]}],
        )
    )
    assert data["rows"] == []
    assert data["matched_rows"] == 0
    assert data["cell_status"] == []
    assert any(note["code"] == "NO_MATCHING_DATA" for note in data["notices"])
    assert data["columns"] == [{"id": "ratio", "kind": "float", "nullable": True}]


def test_all_null_operator_columns_retain_expected_types(execute):
    absent = [{"field": "staff.education", "op": "eq", "values": ["missing_education"]}]
    expr = binary(
        "divide", aggregate("staff.count", where=absent), aggregate("staff.count")
    )
    data = execute(
        request({"ratio": expr, "count": aggregate("staff.count", where=absent)})
    )
    assert data["rows"] == [{"ratio": None, "count": None}]
    assert {column["id"]: column["kind"] for column in data["columns"]} == {
        "ratio": "float",
        "count": "integer",
    }
    assert all(column["nullable"] for column in data["columns"])
    assert data["outputs"][0]["unit"] == "dimensionless"
    standard = execute(request({"ratio": ratio()}))
    assert standard["outputs"][0]["unit"] == "vehicles/persons"


def test_null_sort_last_and_stable_group_ties(execute, derived_catalog):
    with duckdb.connect(str(derived_catalog.database_path)) as connection:
        connection.execute(
            "UPDATE population SET people=0 WHERE municipality_id=2401"
        ).fetchall()
    data = execute(
        request(
            {"ratio": ratio()},
            group_by=["municipality"],
            order_by=[{"field": "ratio", "direction": "desc"}],
        ),
        snapshot=derived_catalog,
    )
    assert data["rows"][-1] == {"municipality": 2401, "ratio": None}
    values = [row["ratio"] for row in data["rows"][:-1]]
    assert values == sorted(values, reverse=True)
    zero = binary(
        "multiply", {"kind": "constant", "value": 0}, aggregate("population.count")
    )
    tied = execute(
        request(
            {"zero": zero},
            group_by=["municipality"],
            order_by=[{"field": "zero", "direction": "desc"}],
        )
    )
    assert [row["municipality"] for row in tied["rows"]] == sorted(
        row["municipality"] for row in tied["rows"]
    )
    assert all(type(row["zero"]) is int and row["zero"] == 0 for row in tied["rows"])


def test_decimal_sort_uses_numeric_value(execute, derived_catalog):
    with duckdb.connect(str(derived_catalog.database_path)) as connection:
        connection.execute(
            "UPDATE revenue SET nominal_chf=900.00 WHERE report_year=2024"
        ).fetchall()
        connection.execute(
            "UPDATE revenue SET nominal_chf=1000.00 WHERE report_year=2025"
        ).fetchall()
    data = execute(
        request(
            {"money": aggregate("revenue.nominal_chf")},
            start=2024,
            group_by=["year"],
            order_by=[{"field": "money", "direction": "asc"}],
        ),
        snapshot=derived_catalog,
    )
    assert data["rows"] == [
        {"year": 2024, "money": "900.00"},
        {"year": 2025, "money": "1000.00"},
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("vehicles.category", 1),
        ("vehicles.category", True),
        ("municipality", "2401"),
        ("municipality", True),
    ],
)
def test_filter_codes_are_not_coerced(catalog, field, value):
    from slayer_app.contracts import AnalysisError

    if field == "municipality":
        payload = request(
            {"people": aggregate("population.count")},
            filters=[{"field": field, "op": "eq", "values": [value]}],
        )
    else:
        payload = request(
            {
                "vehicles": aggregate(
                    "vehicles.count",
                    where=[{"field": field, "op": "eq", "values": [value]}],
                )
            }
        )
    with pytest.raises(AnalysisError) as raised:
        compile_request(catalog, payload)
    assert raised.value.code == "E_INVALID_REQUEST"


@pytest.mark.parametrize("field", ["sql", "source_model", "variables", "timeout"])
def test_native_query_escape_hatches_are_not_public(field):
    from pydantic import ValidationError
    from slayer_app.contracts import AnalysisRequest

    payload = request({"people": aggregate("population.count")})
    payload[field] = "SELECT 1"
    with pytest.raises(ValidationError):
        AnalysisRequest.model_validate(payload)


def test_unexpected_nonfinite_native_value_is_safe_error(execute):
    from slayer_app.contracts import AnalysisError

    def nonfinite(compiled, response):
        rows = [dict(row) for row in response.data]
        rows[0][compiled.native_query.source_model + ".m0"] = float("inf")
        return response.model_copy(update={"data": rows})

    with pytest.raises(AnalysisError) as raised:
        execute(
            request({"people": aggregate("population.count")}),
            transform_response=nonfinite,
        )
    assert raised.value.code == "E_ENGINE_FAILURE"
    assert raised.value.details == {"quality_code": "NON_FINITE_RESULT"}


@pytest.mark.parametrize("warning_kind", ["broadcast_grain", "future_unknown_category"])
def test_native_structured_warning_cannot_silently_change_plan(execute, warning_kind):
    from slayer.core.warnings import SlayerWarning
    from slayer_app.contracts import AnalysisError

    def with_warning(compiled, response):
        return response.model_copy(
            update={"warnings": [SlayerWarning(kind=warning_kind)]}
        )

    with pytest.raises(AnalysisError) as raised:
        execute(
            request({"people": aggregate("population.count")}),
            transform_response=with_warning,
        )
    assert raised.value.code == "E_NATIVE_PLAN_UNSUPPORTED"


@pytest.mark.parametrize("change", [{"population": None}, {"columns": ["unexpected"]}])
def test_native_population_and_columns_are_required(execute, change):
    from slayer_app.contracts import AnalysisError

    with pytest.raises(AnalysisError) as raised:
        execute(
            request({"people": aggregate("population.count")}),
            transform_response=lambda compiled, response: response.model_copy(
                update=change
            ),
        )
    assert raised.value.code in ("E_NATIVE_PLAN_UNSUPPORTED", "E_ENGINE_FAILURE")
