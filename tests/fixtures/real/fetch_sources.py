"""Fetch the public Parquet resources explicitly listed in the supplied catalogue.

This is fixture preparation, not an application catalogue import pipeline.
"""
from __future__ import annotations

import concurrent.futures
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import urllib.request
import xml.etree.ElementTree as ET

import duckdb

HERE = Path(__file__).resolve().parent
UPLOAD = HERE.parents[1] / "upload"
CATALOG = UPLOAD / "catalog-e4560849-cd01-4e19-ac09-11f5d3036fb1.duckdb"
PUBLISHED = UPLOAD / "published-catalog-e4560849-cd01-4e19-ac09-11f5d3036fb1.xtf"
SELECTED = {
    "ch_so_bevoelkerung_gemeinde_alter_2025": "population_age",
    "ch_so_bevoelkerung_gemeinde_geschlecht_2025": "population_sex_nationality",
    "ch_so_fahrzeugbestand_2025": "vehicles",
    "ch_so_av_nachfuehrungsstatistik_personal": "staff",
    "ch_so_av_nachfuehrungsstatistik_umsatz": "revenue",
    "ch_so_gws_gebaeude_heizung": "heating",
    "ch_so_gws_gebaeude_kategorie": "building_category",
    "ch_so_ebau_statistik_dossiers": "ebau",
    "ch_so_staatssteuerertraege_gemeinden_2025": "taxes",
}


def now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def local_name(tag):
    return tag.rsplit("}", 1)[-1]


def catalogue_metadata():
    root = ET.parse(PUBLISHED).getroot()
    result = {}
    for element in root.iter():
        if local_name(element.tag) not in {"Dataset", "DatasetIssue", "DatasetSeries"}:
            continue
        children = {local_name(e.tag): e.text for e in element}
        identifier = children.get("identifier")
        if not identifier:
            continue
        texts = []
        for node in element.iter():
            if local_name(node.tag) in {"license", "accessRights", "rights", "issued", "modified", "temporalStart", "temporalEnd", "description", "surveyMethod", "title", "downloadUrl", "downloadURL", "accessUrl", "accessURL"} and node.text:
                texts.append({"field": local_name(node.tag), "value": node.text})
        result[identifier] = {"fields": children, "details": texts}
    return result


def fetch_one(item):
    view, url, alias = item
    started = now()
    req = urllib.request.Request(url, headers={"User-Agent": "AGI-SLayer-Fixture-Preparation/0.1"})
    with urllib.request.urlopen(req, timeout=45) as response:
        payload = response.read(50 * 1024 * 1024 + 1)
        if len(payload) > 50 * 1024 * 1024:
            raise ValueError("Resource exceeds fixture download size guard")
        headers = {key.lower(): value for key, value in response.headers.items()}
        final_url = response.geturl()
    path = HERE / "raw" / f"{alias}.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    with duckdb.connect() as con:
        columns = con.execute("DESCRIBE SELECT * FROM read_parquet(?)", [str(path)]).fetchall()
        row_count = con.execute("SELECT COUNT(*) FROM read_parquet(?)", [str(path)]).fetchone()[0]
    return {
        "alias": alias,
        "catalog_view": f"opendata.{view}",
        "source_url": url,
        "final_url": final_url,
        "retrieved_at_utc": started,
        "completed_at_utc": now(),
        "path": str(path.relative_to(HERE)),
        "format": "parquet",
        "selection": "complete source file, no row selection or value changes",
        "bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "http_etag": headers.get("etag"),
        "http_last_modified": headers.get("last-modified"),
        "http_content_type": headers.get("content-type"),
        "row_count": row_count,
        "columns": [{"name": c[0], "type": c[1]} for c in columns],
    }


def main():
    con = duckdb.connect(str(CATALOG), read_only=True)
    views = con.execute("SELECT view_name, sql FROM duckdb_views() WHERE schema_name='opendata'").fetchall()
    con.close()
    jobs = []
    for view, statement in views:
        if view in SELECTED:
            matches = re.findall(r"read_parquet\('([^']+)'\)", statement)
            if len(matches) != 1 or not matches[0].startswith("https://"):
                raise ValueError(f"Unexpected view definition for {view}")
            jobs.append((view, matches[0], SELECTED[view]))
    if len(jobs) != len(SELECTED):
        raise ValueError("A requested source view is missing")
    sources, failures = [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        for job, future in [(job, pool.submit(fetch_one, job)) for job in jobs]:
            try:
                source = future.result()
                sources.append(source)
                print(json.dumps({"alias": source["alias"], "rows": source["row_count"], "bytes": source["bytes"], "fields": source["columns"]}), flush=True)
            except Exception as error:
                failure = {"job": list(job), "error": repr(error)}
                failures.append(failure)
                print(json.dumps({"failure": failure}), flush=True)
    manifest = {
        "manifest_version": 1,
        "prepared_at_utc": now(),
        "purpose": "Actual public source snapshots for SLayer coding-agent specification and offline regression tests",
        "catalogue_release_id": "e4560849-cd01-4e19-ac09-11f5d3036fb1",
        "catalogue_path": str(CATALOG),
        "catalogue_sha256": hashlib.sha256(CATALOG.read_bytes()).hexdigest(),
        "metadata_path": str(PUBLISHED),
        "metadata_sha256": hashlib.sha256(PUBLISHED.read_bytes()).hexdigest(),
        "sources": sorted(sources, key=lambda s: s["alias"]),
        "failures": failures,
    }
    (HERE / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    (HERE / "catalogue_metadata.json").write_text(json.dumps(catalogue_metadata(), indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
