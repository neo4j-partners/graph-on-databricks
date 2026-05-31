-- Bronze: Raw parts/components catalog ingested from landing volume.

CREATE OR REFRESH STREAMING TABLE bronze_parts
COMMENT 'Raw parts and components catalog ingested from the landing volume. Append-only.'
CLUSTER BY (category)
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
  '${volume_path}/parts/',
  format => 'parquet'
);
