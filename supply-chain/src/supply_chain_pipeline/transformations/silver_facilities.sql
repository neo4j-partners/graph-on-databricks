-- Silver: Cleaned, typed, and validated facility (plant/warehouse) records.

CREATE OR REFRESH STREAMING TABLE silver_facilities (
  facility_id              STRING    COMMENT 'Unique facility identifier (FAC-XXXXX)',
  facility_name            STRING    COMMENT 'Human-readable facility name including city and type',
  facility_type            STRING    COMMENT 'Operational type: Manufacturing, Assembly, or Warehouse',
  region                   STRING    COMMENT 'US geographic region (Midwest, South, West, etc.)',
  city                     STRING    COMMENT 'City where the facility is located',
  state                    STRING    COMMENT 'US state abbreviation',
  country                  STRING    COMMENT 'Country of the facility',
  capacity_units           INT       COMMENT 'Maximum throughput capacity in units per period',
  current_utilization_pct  DECIMAL(5,1) COMMENT 'Current capacity utilization percentage (50–95%)',
  manager_name             STRING    COMMENT 'Full name of the facility manager',
  opened_year              INT       COMMENT 'Year the facility became operational',
  _ingested_at             TIMESTAMP COMMENT 'Timestamp when the record was ingested at the bronze layer',
  CONSTRAINT pk_facility        EXPECT (facility_id IS NOT NULL)                                    ON VIOLATION DROP ROW,
  CONSTRAINT valid_type         EXPECT (facility_type IN ('Manufacturing','Assembly','Warehouse'))   ON VIOLATION DROP ROW,
  CONSTRAINT positive_capacity  EXPECT (capacity_units > 0)                                         ON VIOLATION DROP ROW,
  CONSTRAINT valid_utilization  EXPECT (current_utilization_pct >= 0 AND current_utilization_pct <= 100) ON VIOLATION DROP ROW
)
COMMENT 'Cleaned and validated facility master data.'
CLUSTER BY (facility_type, region)
TBLPROPERTIES ('delta.enableChangeDataFeed' = 'true')
AS
SELECT
  facility_id,
  facility_name,
  facility_type,
  region,
  city,
  state,
  country,
  CAST(capacity_units          AS INT)         AS capacity_units,
  CAST(current_utilization_pct AS DECIMAL(5,1)) AS current_utilization_pct,
  manager_name,
  CAST(opened_year             AS INT)         AS opened_year,
  _ingested_at
FROM STREAM bronze_facilities
WHERE facility_id IS NOT NULL;
