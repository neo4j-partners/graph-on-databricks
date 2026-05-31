-- Bronze: Raw purchase order records from facilities to suppliers.

CREATE OR REFRESH STREAMING TABLE bronze_purchase_orders
COMMENT 'Raw purchase orders from facilities to suppliers for specific parts.'
CLUSTER BY (order_date, status)
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
  '${volume_path}/purchase_orders/',
  format => 'parquet'
);
