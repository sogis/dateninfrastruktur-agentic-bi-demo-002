"""F01–F16: full real-data comparisons through the public compiler and SLayer."""

from __future__ import annotations

from decimal import Decimal

import duckdb
import pytest


def aggregate(metric, **kwargs):
    return {"kind": "aggregate", "metric": metric, **kwargs}


def binary(op, left, right, **kwargs):
    return {"kind": "binary", "op": op, "left": left, "right": right, **kwargs}


def request(outputs, *, group_by=(), start=2025, end=2025, **kwargs):
    return {
        "period": {"from_year": start, "to_year": end},
        "group_by": list(group_by),
        "outputs": [{"id": name, "expr": expr} for name, expr in outputs.items()],
        "limit": 1000,
        **kwargs,
    }


def selected_vehicles(codes=("01", "60")):
    return aggregate(
        "vehicles.count",
        where=[{"field": "vehicles.category", "op": "in", "values": list(codes)}],
    )


def ratio(codes=("01", "60"), **denominator_kwargs):
    return binary(
        "divide",
        selected_vehicles(codes),
        aggregate("population.count", **denominator_kwargs),
        scale=1000.0,
    )


def oracle_rows(oracle, key):
    entry = oracle[key]
    return [dict(zip(entry["columns"], row)) for row in entry["rows"]]


def assert_rows(actual, expected, keys):
    assert len(actual) == len(expected)
    actual = sorted(actual, key=lambda row: tuple(row[key] for key in keys))
    expected = sorted(expected, key=lambda row: tuple(row[key] for key in keys))
    for got, want in zip(actual, expected):
        assert set(got) == set(want)
        for field, value in want.items():
            if isinstance(value, float):
                assert got[field] == pytest.approx(value, rel=0, abs=1e-9), (
                    field,
                    got,
                    want,
                )
            else:
                assert got[field] == value, (field, got, want)
                if isinstance(value, int):
                    assert type(got[field]) is int


def district_ids(catalog):
    # The independent oracle contains district names. Resolve the checked
    # unique mapping once; ambiguous or missing labels are never guessed.
    with duckdb.connect(str(catalog.database_path), read_only=True) as connection:
        pairs = connection.execute(
            "SELECT DISTINCT district_name,district_id FROM municipalities"
        ).fetchall()
    result = dict(pairs)
    assert len(result) == len(pairs) == 10
    assert len(set(result.values())) == 10
    return result


def test_F01_population_total_and_all_106_municipalities(execute, oracle):
    data = execute(request({"people": aggregate("population.count")}))
    assert data["rows"] == [
        {"people": oracle_rows(oracle, "population_total")[0]["people"]}
    ]
    assert type(data["rows"][0]["people"]) is int
    municipal = execute(
        request({"people": aggregate("population.count")}, group_by=["municipality"])
    )
    expected = [
        {"municipality": row["municipality_id"], "people": row["people"]}
        for row in oracle_rows(oracle, "population_by_municipality")
    ]
    assert_rows(municipal["rows"], expected, ["municipality"])
    assert len(municipal["rows"]) == 106


def test_F02_population_and_vehicles_all_municipalities(execute, oracle):
    data = execute(
        request(
            {
                "people": aggregate("population.count"),
                "vehicles": aggregate("vehicles.count"),
            },
            group_by=["municipality"],
        )
    )
    expected = [
        {
            "municipality": row["municipality_id"],
            "people": row["people"],
            "vehicles": row["vehicles"],
        }
        for row in oracle_rows(oracle, "population_vehicles_by_municipality")
    ]
    assert_rows(data["rows"], expected, ["municipality"])
    assert sum(row["people"] for row in data["rows"]) == 293081
    assert (
        sum(row["people"] for row in data["rows"])
        != oracle_rows(oracle, "negative_control_naive_population_vehicle_join")[0][
            "incorrectly_repeated_population"
        ]
    )


def test_F03_population_and_vehicles_all_districts(execute, oracle, catalog):
    data = execute(
        request(
            {
                "people": aggregate("population.count"),
                "vehicles": aggregate("vehicles.count"),
            },
            group_by=["district"],
        )
    )
    mapping = district_ids(catalog)
    expected = [
        {
            "district": mapping[row["district"]],
            "people": row["people"],
            "vehicles": row["vehicles"],
        }
        for row in oracle_rows(oracle, "population_vehicles_by_district")
    ]
    assert_rows(data["rows"], expected, ["district"])


def test_F04_local_01_60_ratio_and_unknown_reference_date(execute, oracle):
    data = execute(
        request(
            {
                "selected": selected_vehicles(),
                "people": aggregate("population.count"),
                "per_1000": ratio(),
            }
        )
    )
    source = oracle_rows(oracle, "canton_vehicle_ratios")[0]
    assert_rows(
        data["rows"],
        [
            {
                "selected": source["selected_vehicles"],
                "people": source["people"],
                "per_1000": source["selected_per_1000_people"],
            }
        ],
        [],
    )
    assert any(
        note["code"] == "SAME_REPORTING_YEAR_REFERENCE_DATE_UNKNOWN"
        and note.get("source") == "vehicles"
        for note in data["notices"]
    )
    metadata = next(item for item in data["outputs"] if item["id"] == "per_1000")
    assert metadata["reference_dates"]["vehicles"]["2025"] is None
    assert metadata["reference_dates"]["population"]["2025"] == "2025-12-31"


def test_F05_local_ratio_all_106_municipalities(execute, oracle):
    data = execute(request({"per_1000": ratio()}, group_by=["municipality"]))
    expected = [
        {
            "municipality": row["municipality_id"],
            "per_1000": row["selected_per_1000_people"],
        }
        for row in oracle_rows(oracle, "population_vehicles_by_municipality")
    ]
    assert_rows(data["rows"], expected, ["municipality"])
    assert next(row for row in data["rows"] if row["municipality"] == 2401)[
        "per_1000"
    ] == pytest.approx(668.7299403943146, rel=0, abs=1e-9)


def test_F06_all_42_categories_with_fixed_population_denominator(execute, oracle):
    expr = binary(
        "divide",
        aggregate("vehicles.count"),
        aggregate("population.count", grain=[]),
        scale=1000.0,
    )
    data = execute(
        request(
            {"vehicles": aggregate("vehicles.count"), "per_1000": expr},
            group_by=["vehicles.category"],
        )
    )
    population = oracle_rows(oracle, "population_total")[0]["people"]
    expected = [
        {
            "vehicles.category": row["vehicle_category_code"],
            "vehicles": row["vehicles"],
            "per_1000": row["vehicles"] / population * 1000,
        }
        for row in oracle_rows(oracle, "vehicles_by_category")
    ]
    assert_rows(data["rows"], expected, ["vehicles.category"])
    assert len(data["rows"]) == 42
    assert any(note["code"] == "COVERAGE_UNKNOWN" for note in data["notices"])


def test_F07_leading_zero_personenwagen_code(execute, oracle):
    data = execute(
        request({"cars": selected_vehicles(["01"]), "per_1000": ratio(["01"])})
    )
    source = oracle_rows(oracle, "canton_vehicle_ratios")[0]
    assert_rows(
        data["rows"],
        [
            {
                "cars": source["passenger_cars"],
                "per_1000": source["cars_per_1000_people"],
            }
        ],
        [],
    )


def test_F08_staff_revenue_and_ratio_2024_2025(execute, oracle):
    data = execute(
        request(
            {
                "staff": aggregate("staff.count"),
                "revenue": aggregate("revenue.nominal_chf"),
                "per_staff": binary(
                    "divide", aggregate("revenue.nominal_chf"), aggregate("staff.count")
                ),
            },
            group_by=["year"],
            start=2024,
        )
    )
    expected = [
        {
            "year": row["report_year"],
            "staff": row["people"],
            "revenue": row["nominal_revenue_chf"],
            "per_staff": row["nominal_chf_per_person"],
        }
        for row in oracle_rows(oracle, "staff_revenue_2024_2025")
    ]
    assert_rows(data["rows"], expected, ["year"])
    assert (
        next(column for column in data["columns"] if column["id"] == "revenue")["kind"]
        == "decimal"
    )
    assert all(
        isinstance(row["revenue"], str)
        and Decimal(row["revenue"]).as_tuple().exponent == -2
        for row in data["rows"]
    )
    assert data["rows"][1]["revenue"] != "13813050.00"


def test_F09_mean_annual_staff_totals(execute, oracle):
    data = execute(
        request(
            {
                "mean_staff": aggregate(
                    "staff.count", temporal_reduce="mean_annual_totals"
                )
            },
            start=2024,
        )
    )
    expected = oracle_rows(oracle, "staff_average_of_annual_totals_2024_2025")[0][
        "average_annual_total"
    ]
    assert data["rows"] == [{"mean_staff": expected}]
    assert expected == 65.5
    assert expected not in (13.1, 131)


def test_F10_nominal_revenue_flow_sum(execute):
    data = execute(request({"revenue": aggregate("revenue.nominal_chf")}, start=2024))
    assert data["rows"] == [{"revenue": "5328676.00"}]


def test_F11_revenue_growth_uses_hidden_base_year(execute, oracle):
    expr = {
        "kind": "period",
        "op": "relative_change",
        "years": 1,
        "value": aggregate("revenue.nominal_chf"),
    }
    data = execute(request({"growth": expr}, group_by=["year"]))
    expected = (
        oracle_rows(oracle, "nominal_growth_2025")[0]["nominal_revenue_growth_pct"]
        / 100
    )
    assert_rows(data["rows"], [{"year": 2025, "growth": expected}], ["year"])
    assert data["visible_period"] == {"from_year": 2025, "to_year": 2025}


def test_F12_growth_of_nominal_revenue_per_staff(execute, oracle):
    value = binary("divide", aggregate("revenue.nominal_chf"), aggregate("staff.count"))
    expr = {"kind": "period", "op": "relative_change", "years": 1, "value": value}
    data = execute(request({"growth": expr}))
    expected = (
        oracle_rows(oracle, "nominal_growth_2025")[0][
            "nominal_revenue_per_person_growth_pct"
        ]
        / 100
    )
    assert_rows(data["rows"], [{"growth": expected}], [])


def test_F13_staff_2025_by_education(execute, oracle):
    data = execute(
        request({"staff": aggregate("staff.count")}, group_by=["staff.education"])
    )
    expected = [
        {"staff.education": row["education"], "staff": row["people"]}
        for row in oracle_rows(oracle, "staff_2025_by_education")
    ]
    assert_rows(data["rows"], expected, ["staff.education"])


def test_F14_heating_share_total_and_all_districts(execute, oracle):
    share = binary(
        "divide",
        aggregate("heating.heat_pump"),
        aggregate("heating.buildings"),
        scale=100.0,
    )
    data = execute(
        request(
            {
                "buildings": aggregate("heating.buildings"),
                "heat_pumps": aggregate("heating.heat_pump"),
                "share": share,
            }
        )
    )
    source = oracle_rows(oracle, "heating_total")[0]
    assert_rows(
        data["rows"],
        [
            {
                "buildings": source["buildings"],
                "heat_pumps": source["heat_pump_buildings"],
                "share": source["heat_pump_share_pct"],
            }
        ],
        [],
    )
    districts = execute(request({"share": share}, group_by=["district"]))
    expected = [
        {"district": row["district_id"], "share": row["heat_pump_share_pct"]}
        for row in oracle_rows(oracle, "heating_by_district")
    ]
    assert_rows(districts["rows"], expected, ["district"])


def test_F15_shared_municipality_filter_reaches_all_leaves(execute, oracle):
    data = execute(
        request(
            {
                "people": aggregate("population.count"),
                "selected": selected_vehicles(),
                "per_1000": ratio(),
            },
            filters=[{"field": "municipality", "op": "eq", "values": [2401]}],
        )
    )
    source = next(
        row
        for row in oracle_rows(oracle, "population_vehicles_by_municipality")
        if row["municipality_id"] == 2401
    )
    assert_rows(
        data["rows"],
        [
            {
                "people": source["people"],
                "selected": source["selected_vehicles"],
                "per_1000": source["selected_per_1000_people"],
            }
        ],
        [],
    )


def test_F16_mean_annual_staff_totals_by_education(execute):
    from conftest import REAL

    # Independent explicit raw-data SQL; no compiler formula or normalized
    # data is reused to derive the expected annual partition.
    with duckdb.connect() as connection:
        rows = connection.execute(
            """WITH annual AS (
            SELECT ausbildung, jahr, SUM(anzahl_mitarbeitende) AS total
            FROM read_parquet(?) WHERE jahr BETWEEN 2024 AND 2025 GROUP BY ausbildung,jahr)
            SELECT ausbildung,AVG(total),COUNT(*) FROM annual GROUP BY ausbildung ORDER BY ausbildung""",
            [str(REAL / "raw" / "staff.parquet")],
        ).fetchall()
    assert all(count == 2 for _, _, count in rows)
    data = execute(
        request(
            {
                "mean_staff": aggregate(
                    "staff.count", temporal_reduce="mean_annual_totals"
                )
            },
            group_by=["staff.education"],
            start=2024,
        )
    )
    assert_rows(
        data["rows"],
        [
            {"staff.education": education, "mean_staff": value}
            for education, value, _ in rows
        ],
        ["staff.education"],
    )


def test_registrations_and_proven_complete_categories(execute, oracle):
    data = execute(
        request(
            {
                "registrations": aggregate("vehicles.registrations"),
                "selected": selected_vehicles(),
            }
        )
    )
    expected = oracle_rows(oracle, "vehicles_total")[0]
    assert data["rows"] == [
        {
            "registrations": expected["registrations"],
            "selected": expected["selected_vehicles"],
        }
    ]
    assert any(
        n["code"] == "SAME_REPORTING_YEAR_REFERENCE_DATE_UNKNOWN"
        for n in data["notices"]
    )
    # The unfiltered published total still discloses the category matrix limit.
    assert any(n["code"] == "COVERAGE_UNKNOWN" for n in data["notices"])
    selected = execute(request({"selected": selected_vehicles()}))
    assert not any(n["code"] == "COVERAGE_UNKNOWN" for n in selected["notices"])
    assert selected["provenance"]["source_snapshots"][0]["source_id"] == "vehicles"


def test_explicit_district_denominator_per_municipality(execute, oracle, catalog):
    expr = binary(
        "divide",
        aggregate("population.count"),
        aggregate("population.count", grain=["district"]),
    )
    data = execute(request({"share": expr}, group_by=["district", "municipality"]))
    mapping = district_ids(catalog)
    totals = {
        mapping[r["district"]]: r["people"]
        for r in oracle_rows(oracle, "population_by_district")
    }
    expected = [
        {
            "district": mapping[r["district"]],
            "municipality": r["municipality_id"],
            "share": r["people"] / totals[mapping[r["district"]]],
        }
        for r in oracle_rows(oracle, "population_by_municipality")
    ]
    assert_rows(data["rows"], expected, ["district", "municipality"])
    assert data["cell_status"] == []


def test_constant_numerator_inherits_denominator_grouping(execute, oracle):
    expr = binary(
        "divide", {"kind": "constant", "value": 1}, aggregate("vehicles.count")
    )
    data = execute(request({"reciprocal": expr}, group_by=["vehicles.category"]))
    expected = [
        {
            "vehicles.category": r["vehicle_category_code"],
            "reciprocal": 1 / r["vehicles"],
        }
        for r in oracle_rows(oracle, "vehicles_by_category")
    ]
    assert_rows(data["rows"], expected, ["vehicles.category"])
