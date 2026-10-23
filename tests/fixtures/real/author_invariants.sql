-- Candidate-release checks against the normalized physical table names.
-- Every row must report violations=0. These are authored SQL checks, not a
-- general coverage engine. A failed candidate must not replace the active bundle.
-- The real duplicate-key source is independently checked by
-- reference_queries.sql::quality_duplicate_population_sex_keys before inclusion.

WITH all_cells AS (
  SELECT 'population' source,report_year,geo_version,municipality_id,cell_id FROM population
  UNION ALL SELECT 'vehicles',report_year,geo_version,municipality_id,cell_id FROM vehicles
  UNION ALL SELECT 'heating',report_year,geo_version,municipality_id,cell_id FROM heating
  UNION ALL SELECT 'building_category',report_year,geo_version,municipality_id,cell_id FROM building_category
  UNION ALL SELECT 'taxes',report_year,geo_version,municipality_id,cell_id FROM taxes
), annual_periods AS (
  SELECT report_year,period_start FROM population
  UNION ALL SELECT report_year,period_start FROM vehicles
  UNION ALL SELECT report_year,period_start FROM staff
  UNION ALL SELECT report_year,period_start FROM revenue
  UNION ALL SELECT report_year,period_start FROM heating
  UNION ALL SELECT report_year,period_start FROM building_category
  UNION ALL SELECT report_year,period_start FROM taxes
)
SELECT 'population_key_unique' check_name,count(*) violations
FROM (SELECT report_year,geo_version,municipality_id FROM population GROUP BY ALL HAVING count(*)<>1)
UNION ALL
SELECT 'vehicle_key_unique',count(*)
FROM (SELECT report_year,geo_version,municipality_id,vehicle_category_code FROM vehicles GROUP BY ALL HAVING count(*)<>1)
UNION ALL
SELECT 'municipality_key_unique',count(*)
FROM (SELECT geo_version,municipality_id FROM municipalities GROUP BY ALL HAVING count(*)<>1)
UNION ALL
SELECT 'staff_key_unique',count(*) FROM (SELECT report_year,education FROM staff GROUP BY ALL HAVING count(*)<>1)
UNION ALL
SELECT 'revenue_key_unique',count(*) FROM (SELECT report_year FROM revenue GROUP BY ALL HAVING count(*)<>1)
UNION ALL
SELECT 'population_to_municipalities_complete',count(*) FROM population p
WHERE NOT EXISTS(SELECT 1 FROM municipalities m WHERE p.geo_version=m.geo_version AND p.municipality_id=m.municipality_id)
UNION ALL
SELECT 'vehicles_to_population_complete',count(*) FROM vehicles v
WHERE NOT EXISTS(SELECT 1 FROM population p WHERE p.report_year=v.report_year AND p.geo_version=v.geo_version AND p.municipality_id=v.municipality_id)
UNION ALL
SELECT 'population_to_vehicles_complete',count(*) FROM population p
WHERE NOT EXISTS(SELECT 1 FROM vehicles v WHERE p.report_year=v.report_year AND p.geo_version=v.geo_version AND p.municipality_id=v.municipality_id)
UNION ALL
SELECT 'vehicle_values_01_60_complete',count(*) FROM population p CROSS JOIN (VALUES ('01'),('60')) wanted(category_code)
WHERE NOT EXISTS(SELECT 1 FROM vehicles v WHERE p.report_year=v.report_year AND p.geo_version=v.geo_version AND p.municipality_id=v.municipality_id AND v.vehicle_category_code=wanted.category_code)
UNION ALL
SELECT 'population_marginal_identities',count(*) FROM population
WHERE people IS NULL OR people<0 OR people<>women+men OR people<>swiss_people+foreign_people
   OR people<>age_0_19+age_20_39+age_40_64+age_65_79+age_80_plus
   OR age_65_plus<>age_65_79+age_80_plus
UNION ALL
SELECT 'cell_id_exact_and_present',count(*) FROM all_cells
WHERE cell_id IS NULL OR cell_id<>concat(geo_version,'|',report_year,'|',municipality_id)
UNION ALL
SELECT 'annual_period_start_is_technical_year_key',count(*) FROM annual_periods
WHERE period_start IS NULL OR period_start<>make_date(report_year,1,1)
UNION ALL
SELECT 'population_snapshot_as_published',count(*) FROM population
WHERE reference_date IS NULL OR reference_date<>DATE '2025-12-31'
UNION ALL
SELECT 'vehicle_unknown_snapshot_not_fabricated',count(*) FROM vehicles WHERE reference_date IS NOT NULL
UNION ALL
SELECT 'gws_heating_marginal_total',count(*) FROM heating
WHERE buildings<>heat_pump+heating_oil+gas+wood+electricity+district_heating+other_or_unknown
UNION ALL
SELECT 'gws_category_marginal_total',count(*) FROM building_category
WHERE buildings<>single_family+multi_family+residential_secondary_use+partially_residential
UNION ALL
SELECT 'gws_matching_building_totals',count(*) FROM heating h FULL JOIN building_category b USING(report_year,geo_version,municipality_id)
WHERE h.buildings IS NULL OR b.buildings IS NULL OR h.buildings<>b.buildings
UNION ALL
SELECT 'ebau_key_unique',count(*) FROM (SELECT period_start FROM ebau GROUP BY ALL HAVING count(*)<>1)
ORDER BY check_name;
