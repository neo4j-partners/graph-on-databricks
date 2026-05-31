-- Bronze: Raw facility (plant / warehouse) records ingested from landing volume.

CREATE OR REFRESH STREAMING TABLE bronze_facilities
COMMENT 'Raw facility records (manufacturing plants, assembly sites, warehouses) from landing volume.'
CLUSTER BY (facility_type, region)
TBLPROPERTIES (
  'delta.autoOptimize.optimizeWrite' = 'true',
  'delta.enableChangeDataFeed'       = 'true'
)
AS
SELECT
  *,
  current_timestamp()      AS _ingested_at,
  _metadata.file_path      AS _source_file
FROM STREAM read_files(
  '${volume_path}/facilities/',
  format => 'parquet'
);
