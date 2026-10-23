-- Each query is an independent direct-SQL oracle over the unmodified source files.
-- Vehicle/population ratios are arithmetic checks for the 2025 editions.
-- They do NOT establish that both sources have the same observation date.

-- QUERY population_total
SELECT COUNT(*) AS municipalities, SUM(Total) AS people,
       SUM(Total_Weiblich) AS women, SUM(Total_Maennlich) AS men,
       SUM(Alter_65_bis_79 + Alter_80_und_mehr) AS people_65_plus
FROM population_age;

-- QUERY population_by_municipality
SELECT BFS_Nr AS municipality_id, Gemeinde AS municipality, Bezirk AS district,
       Total AS people
FROM population_age
ORDER BY BFS_Nr;

-- QUERY population_by_district
SELECT Bezirk AS district, COUNT(*) AS municipalities, SUM(Total) AS people
FROM population_age
GROUP BY Bezirk
ORDER BY Bezirk;

-- QUERY vehicles_by_category
SELECT FZART_CD AS vehicle_category_code, FZART_NA AS vehicle_category,
       COUNT(*) AS observed_municipalities, SUM(Anzahl) AS vehicles,
       SUM(Anzahl_ohne_WS) AS registrations_with_shared_plates_counted_once
FROM vehicles
GROUP BY FZART_CD, FZART_NA
ORDER BY FZART_CD, FZART_NA;

-- QUERY vehicles_total
SELECT COUNT(*) AS rows, COUNT(DISTINCT GDENR) AS municipalities,
       SUM(Anzahl) AS vehicles, SUM(Anzahl_ohne_WS) AS registrations,
       SUM(Anzahl) FILTER (WHERE FZART_CD='01') AS passenger_cars,
       SUM(Anzahl) FILTER (WHERE FZART_CD='60') AS motorcycles,
       SUM(Anzahl) FILTER (WHERE FZART_CD IN ('01','60')) AS selected_vehicles
FROM vehicles;

-- QUERY population_vehicles_by_municipality
WITH v AS (
  SELECT GDENR AS municipality_id,
         SUM(Anzahl) AS vehicles,
         SUM(Anzahl) FILTER (WHERE FZART_CD='01') AS passenger_cars,
         SUM(Anzahl) FILTER (WHERE FZART_CD IN ('01','60')) AS selected_vehicles
  FROM vehicles GROUP BY GDENR
)
SELECT p.BFS_Nr AS municipality_id, p.Gemeinde AS municipality, p.Bezirk AS district,
       p.Total AS people, v.vehicles, v.passenger_cars, v.selected_vehicles,
       1000.0*v.passenger_cars/NULLIF(p.Total,0) AS cars_per_1000_people,
       1000.0*v.selected_vehicles/NULLIF(p.Total,0) AS selected_per_1000_people
FROM population_age p LEFT JOIN v ON p.BFS_Nr=v.municipality_id
ORDER BY p.BFS_Nr;

-- QUERY population_vehicles_by_district
WITH v AS (
  SELECT GDENR AS municipality_id, SUM(Anzahl) AS vehicles,
         SUM(Anzahl) FILTER (WHERE FZART_CD='01') AS passenger_cars,
         SUM(Anzahl) FILTER (WHERE FZART_CD IN ('01','60')) AS selected_vehicles
  FROM vehicles GROUP BY GDENR
)
SELECT p.Bezirk AS district, SUM(p.Total) AS people, SUM(v.vehicles) AS vehicles,
       SUM(v.passenger_cars) AS passenger_cars, SUM(v.selected_vehicles) AS selected_vehicles,
       1000.0*SUM(v.passenger_cars)/NULLIF(SUM(p.Total),0) AS cars_per_1000_people,
       1000.0*SUM(v.selected_vehicles)/NULLIF(SUM(p.Total),0) AS selected_per_1000_people
FROM population_age p LEFT JOIN v ON p.BFS_Nr=v.municipality_id
GROUP BY p.Bezirk
ORDER BY p.Bezirk;

-- QUERY canton_vehicle_ratios
WITH p AS (SELECT SUM(Total) AS people FROM population_age),
v AS (SELECT SUM(Anzahl) AS vehicles,
             SUM(Anzahl) FILTER (WHERE FZART_CD='01') AS passenger_cars,
             SUM(Anzahl) FILTER (WHERE FZART_CD IN ('01','60')) AS selected_vehicles FROM vehicles)
SELECT p.people,v.vehicles,v.passenger_cars,v.selected_vehicles,
       1000.0*v.passenger_cars/NULLIF(p.people,0) AS cars_per_1000_people,
       1000.0*v.selected_vehicles/NULLIF(p.people,0) AS selected_per_1000_people
FROM p CROSS JOIN v;

-- QUERY fixed_population_denominator_by_category
WITH p AS (SELECT SUM(Total) AS people FROM population_age)
SELECT v.FZART_CD AS vehicle_category_code, v.FZART_NA AS vehicle_category,
       SUM(v.Anzahl) AS vehicles, MAX(p.people) AS canton_population_reference,
       1000.0*SUM(v.Anzahl)/NULLIF(MAX(p.people),0) AS vehicles_per_1000_people
FROM vehicles v CROSS JOIN p
WHERE v.FZART_CD IN ('01','60')
GROUP BY v.FZART_CD,v.FZART_NA ORDER BY v.FZART_CD;

-- QUERY staff_by_year
SELECT jahr AS report_year,SUM(anzahl_mitarbeitende) AS people,
       COUNT(*) AS education_rows
FROM staff GROUP BY jahr ORDER BY jahr;

-- QUERY staff_revenue_by_year
WITH s AS (SELECT jahr,SUM(anzahl_mitarbeitende) AS people FROM staff GROUP BY jahr)
SELECT s.jahr AS report_year,s.people,CAST(r.umsatz AS DECIMAL(18,2)) AS nominal_revenue_chf,
       CAST(r.umsatz AS DECIMAL(18,2))/NULLIF(s.people,0) AS nominal_chf_per_person
FROM s LEFT JOIN revenue r USING(jahr) ORDER BY s.jahr;

-- QUERY staff_revenue_2024_2025
WITH s AS (SELECT jahr,SUM(anzahl_mitarbeitende) AS people FROM staff GROUP BY jahr)
SELECT s.jahr AS report_year,s.people,CAST(r.umsatz AS DECIMAL(18,2)) AS nominal_revenue_chf,
       CAST(r.umsatz AS DECIMAL(18,2))/NULLIF(s.people,0) AS nominal_chf_per_person
FROM s JOIN revenue r USING(jahr) WHERE s.jahr IN(2024,2025) ORDER BY s.jahr;

-- QUERY staff_average_of_annual_totals_2024_2025
WITH s AS (SELECT jahr,SUM(anzahl_mitarbeitende) AS people FROM staff WHERE jahr IN(2024,2025) GROUP BY jahr)
SELECT AVG(people) AS average_annual_total,COUNT(*) AS observed_years FROM s;

-- QUERY nominal_growth_2025
WITH s AS(SELECT jahr,SUM(anzahl_mitarbeitende) AS people FROM staff GROUP BY jahr),
x AS(SELECT s.jahr,s.people,CAST(r.umsatz AS DECIMAL(18,2)) AS revenue FROM s JOIN revenue r USING(jahr))
SELECT (curr.revenue/NULLIF(prev.revenue,0)-1)*100 AS nominal_revenue_growth_pct,
       ((curr.revenue/curr.people)/(prev.revenue/prev.people)-1)*100 AS nominal_revenue_per_person_growth_pct
FROM x curr JOIN x prev ON prev.jahr=curr.jahr-1 WHERE curr.jahr=2025;

-- QUERY staff_2025_by_education
SELECT ausbildung AS education,anzahl_mitarbeitende AS people
FROM staff WHERE jahr=2025 ORDER BY ausbildung;

-- QUERY ebau_by_quarter
SELECT year(berichtsmonat) AS report_year,quarter(berichtsmonat) AS report_quarter,
       COUNT(*) AS months_present,MIN(berichtsmonat) AS first_present_month,
       MAX(berichtsmonat) AS last_present_month,
       SUM(anzahl_ueber_ebau_eingereichte_dossiers) AS submitted_dossiers,
       arg_max(anzahl_gemeinden_in_ebau,berichtsmonat) AS municipalities_last_present_month
FROM ebau GROUP BY report_year,report_quarter ORDER BY report_year,report_quarter;

-- QUERY heating_by_district
SELECT jahr AS report_year,bfs_bezirk_nr AS district_id,bezirk AS district,
       SUM(gebaeude_total) AS buildings,SUM(geb_hz_waermepumpe) AS heat_pump_buildings,
       100.0*SUM(geb_hz_waermepumpe)/NULLIF(SUM(gebaeude_total),0) AS heat_pump_share_pct
FROM heating GROUP BY jahr,bfs_bezirk_nr,bezirk ORDER BY jahr,bfs_bezirk_nr;

-- QUERY heating_total
SELECT jahr AS report_year,SUM(gebaeude_total) AS buildings,
       SUM(geb_hz_waermepumpe) AS heat_pump_buildings,
       100.0*SUM(geb_hz_waermepumpe)/NULLIF(SUM(gebaeude_total),0) AS heat_pump_share_pct
FROM heating GROUP BY jahr ORDER BY jahr;

-- QUERY quality_duplicate_population_sex_keys
SELECT BFS_Nr AS municipality_id,COUNT(*) AS rows,
       string_agg(Gemeinde,', ' ORDER BY Gemeinde) AS municipality_names,
       SUM(Total) AS people_in_duplicate_rows
FROM population_sex_nationality GROUP BY BFS_Nr HAVING COUNT(*)>1 ORDER BY BFS_Nr;

-- QUERY quality_tax_geography_difference
SELECT p.BFS_Nr AS municipality_id,p.Gemeinde AS municipality,p.Total AS people
FROM population_age p LEFT JOIN taxes t ON p.BFS_Nr=t.gemeinde_bfs_nr
WHERE t.gemeinde_bfs_nr IS NULL ORDER BY p.BFS_Nr;

-- QUERY quality_fusion_context
SELECT p.BFS_Nr AS municipality_id,p.Gemeinde AS municipality,p.Total AS people,
       t.staatssteuer_total_tchf AS tax_total_tchf_if_same_number
FROM population_age p LEFT JOIN taxes t ON p.BFS_Nr=t.gemeinde_bfs_nr
WHERE p.BFS_Nr IN(2520,2525,2529) ORDER BY p.BFS_Nr;

-- QUERY negative_control_naive_population_vehicle_join
SELECT SUM(p.Total) AS incorrectly_repeated_population,
       SUM(v.Anzahl) AS vehicles
FROM population_age p JOIN vehicles v ON p.BFS_Nr=v.GDENR;

-- QUERY negative_control_naive_staff_revenue_join_2025
SELECT SUM(s.anzahl_mitarbeitende) AS staff,
       SUM(CAST(r.umsatz AS DECIMAL(18,2))) AS incorrectly_repeated_revenue
FROM staff s JOIN revenue r USING(jahr) WHERE s.jahr=2025;

-- QUERY negative_control_average_staff_rows_2024_2025
SELECT AVG(anzahl_mitarbeitende) AS wrong_average_of_education_rows,
       SUM(anzahl_mitarbeitende) AS disallowed_sum_of_stock_years
FROM staff WHERE jahr IN(2024,2025);
