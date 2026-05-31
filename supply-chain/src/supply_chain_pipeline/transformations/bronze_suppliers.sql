-- Bronze: Raw supplier records ingested from landing volume via Auto Loader.
-- No transforms — adds ingestion metadata only.

CREATE OR REFRESH STREAMING TABLE bronze_suppliers
COMMENT 'Raw supplier records ingested from the landing volume. Append-only.'
CLUSTER BY (country, tier)
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
  '${volume_path}/suppliers/',
  format => 'parquet'
);
