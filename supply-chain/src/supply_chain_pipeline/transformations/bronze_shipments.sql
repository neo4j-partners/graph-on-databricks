-- Bronze: Raw shipment records linked to purchase orders.

CREATE OR REFRESH STREAMING TABLE bronze_shipments
COMMENT 'Raw physical shipment records against purchase orders, including carrier and status.'
CLUSTER BY (ship_date, status)
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
  '${volume_path}/shipments/',
  format => 'parquet'
);
