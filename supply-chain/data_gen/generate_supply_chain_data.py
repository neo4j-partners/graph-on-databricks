"""
Supply Chain Synthetic Data Generator — Phase 1
================================================
Generates realistic manufacturing supply chain data using Spark + Faker + Pandas UDFs.

Tables produced (as Parquet in Unity Catalog Volume):
  suppliers        200 rows  — supplier companies
  parts            500 rows  — parts / components catalog
  facilities        50 rows  — manufacturing plants and warehouses
  bom            ~2000 rows  — bill of materials (parent-child part relationships)
  purchase_orders  8000 rows  — POs from facilities to suppliers
  shipments      ~12000 rows  — physical shipments against POs

Output Volume:
  /Volumes/supplychain/supply_chain_raw/landing/<table>/

Generation order matters:
  1. suppliers, parts, facilities  → written to temp Delta tables (no .cache() on serverless)
  2. bom                           → joins temp parts table for valid FK pairs
  3. purchase_orders               → joins all three master temp tables
  4. shipments                     → joins temp purchase_orders table

Run with Databricks Connect (serverless):
  python data_gen/generate_supply_chain_data.py
"""

from databricks.connect import DatabricksSession, DatabricksEnv
from pyspark.sql import functions as F
from pyspark.sql.types import StringType, DoubleType, IntegerType, BooleanType
from pyspark.sql.window import Window
import pandas as pd
import numpy as np
from datetime import date, timedelta

# ─── Configuration ────────────────────────────────────────────────────────────
CATALOG     = "supplychain"
RAW_SCHEMA  = "supply_chain_raw"
TEMP_SCHEMA = "supply_chain_temp"
VOLUME_PATH = f"/Volumes/{CATALOG}/{RAW_SCHEMA}/landing"
TEMP_DB     = f"{CATALOG}.{TEMP_SCHEMA}"

N_SUPPLIERS   = 200
N_PARTS       = 500
N_FACILITIES  = 50
N_BOM         = 2_000
N_POS         = 8_000

END_DATE    = date(2026, 4, 15)
START_DATE  = END_DATE - timedelta(days=548)   # ~18 months history
DATE_RANGE  = (END_DATE - START_DATE).days

# ─── Session ──────────────────────────────────────────────────────────────────
env = DatabricksEnv().withDependencies("faker", "numpy")
spark = DatabricksSession.builder.withEnvironment(env).serverless(True).getOrCreate()
spark.conf.set("spark.sql.shuffle.partitions", "8")

print("Spark session ready.")

# ─── Infrastructure ───────────────────────────────────────────────────────────
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{RAW_SCHEMA}")
spark.sql(f"CREATE VOLUME IF NOT EXISTS {CATALOG}.{RAW_SCHEMA}.landing")
spark.sql(f"CREATE SCHEMA IF NOT EXISTS {CATALOG}.{TEMP_SCHEMA}")
print("Infrastructure ready.\n")


# ══════════════════════════════════════════════════════════════════════════════
# Pandas UDFs  (Faker / numpy — all imports must be inside the UDF body)
# ══════════════════════════════════════════════════════════════════════════════

@F.pandas_udf(StringType())
def gen_supplier_name(ids: pd.Series) -> pd.Series:
    from faker import Faker
    fake = Faker(); Faker.seed(0)
    return pd.Series([f"{fake.company()} Manufacturing" for _ in ids])


@F.pandas_udf(StringType())
def gen_company_email(ids: pd.Series) -> pd.Series:
    from faker import Faker
    fake = Faker(); Faker.seed(1)
    return pd.Series([fake.company_email() for _ in ids])


@F.pandas_udf(StringType())
def gen_city_by_country(countries: pd.Series) -> pd.Series:
    import random
    city_map = {
        "United States":  ["Detroit", "Chicago", "Houston", "Los Angeles", "Charlotte",
                           "Nashville", "Columbus", "Indianapolis", "Cleveland", "Phoenix"],
        "Germany":        ["Munich", "Stuttgart", "Hamburg", "Frankfurt", "Dusseldorf"],
        "Japan":          ["Tokyo", "Osaka", "Nagoya", "Yokohama", "Kyoto"],
        "China":          ["Shanghai", "Shenzhen", "Guangzhou", "Beijing", "Chengdu"],
        "South Korea":    ["Seoul", "Busan", "Incheon", "Daegu"],
        "Mexico":         ["Monterrey", "Guadalajara", "Tijuana", "Saltillo"],
        "Canada":         ["Toronto", "Montreal", "Vancouver", "Windsor"],
        "India":          ["Mumbai", "Chennai", "Pune", "Bangalore"],
        "Brazil":         ["Sao Paulo", "Belo Horizonte", "Curitiba", "Campinas"],
        "United Kingdom": ["Birmingham", "Manchester", "Coventry", "Sheffield"],
        "France":         ["Paris", "Lyon", "Toulouse", "Nantes"],
        "Italy":          ["Turin", "Milan", "Genoa", "Bologna"],
    }
    rng = random.Random(42)
    return pd.Series([rng.choice(city_map.get(c, ["Unknown"])) for c in countries])


@F.pandas_udf(StringType())
def gen_certifications(tiers: pd.Series) -> pd.Series:
    import random
    pool = {
        "Tier-1": ["ISO-9001, AS9100", "ISO-9001, IATF-16949, AS9100",
                   "ISO-9001, ISO-14001, IATF-16949"],
        "Tier-2": ["ISO-9001", "ISO-9001, IATF-16949", "ISO-9001, ISO-14001"],
        "Tier-3": ["ISO-9001", "None", "ISO-9001"],
    }
    rng = random.Random(42)
    return pd.Series([rng.choice(pool.get(t, ["None"])) for t in tiers])


@F.pandas_udf(DoubleType())
def gen_reliability_score(tiers: pd.Series) -> pd.Series:
    rng = np.random.default_rng(42)
    out = []
    for t in tiers:
        s = rng.beta(9, 1.5) if t == "Tier-1" else (rng.beta(5, 2) if t == "Tier-2" else rng.beta(3, 2))
        out.append(float(np.clip(round(s, 3), 0.50, 1.00)))
    return pd.Series(out)


@F.pandas_udf(DoubleType())
def gen_annual_revenue(tiers: pd.Series) -> pd.Series:
    rng = np.random.default_rng(42)
    mu = {"Tier-1": 20.0, "Tier-2": 17.5, "Tier-3": 15.5}
    return pd.Series([round(float(rng.lognormal(mu.get(t, 15.5), 0.8)), 2) for t in tiers])


@F.pandas_udf(StringType())
def gen_part_name(data: pd.Series) -> pd.Series:
    """data format: '<category>|<row_index>'"""
    import random
    bases = {
        "Raw Material": ["Steel Sheet", "Aluminum Ingot", "Copper Wire", "Rubber Compound",
                         "Plastic Pellet", "Carbon Fiber Roll", "Titanium Rod",
                         "Glass Fiber Mat", "Epoxy Resin", "Zinc Alloy Bar",
                         "Magnesium Sheet", "Nickel Alloy", "ABS Resin", "Nylon Granule"],
        "Sub-Assembly": ["Brake Assembly", "Engine Mount", "Transmission Unit",
                         "Cooling Module", "Fuel Injector Assembly", "Suspension Kit",
                         "Steering Column", "Exhaust Manifold", "Turbocharger Unit",
                         "Differential Assembly", "Hydraulic Actuator", "Gear Box Sub-Assy",
                         "Power Steering Pump", "Drive Shaft Assembly", "Clutch Assembly"],
        "Component":    ["Bearing Set", "Fastener Pack", "Gasket Kit", "Oil Seal Ring",
                         "Air Filter Element", "Pressure Sensor", "Control Valve Body",
                         "Solenoid Actuator", "Mounting Bracket", "Hex Bolt Set",
                         "O-Ring Kit", "Spring Assembly", "Heat Shield", "Wire Harness Clip"],
    }
    rng = random.Random(42)
    out = []
    for item in data:
        cat, idx = item.split("|")
        name = rng.choice(bases.get(cat, ["Unknown Part"]))
        out.append(f"{name} #{int(idx) + 1:03d}")
    return pd.Series(out)


@F.pandas_udf(DoubleType())
def gen_unit_cost(cats: pd.Series) -> pd.Series:
    rng = np.random.default_rng(42)
    mu = {"Raw Material": 2.5, "Sub-Assembly": 5.5, "Component": 3.5}
    return pd.Series([round(float(rng.lognormal(mu.get(c, 3.5), 0.8)), 2) for c in cats])


@F.pandas_udf(StringType())
def gen_manager_name(ids: pd.Series) -> pd.Series:
    from faker import Faker
    fake = Faker(); Faker.seed(10)
    return pd.Series([fake.name() for _ in ids])


@F.pandas_udf(StringType())
def gen_facility_city(regions: pd.Series) -> pd.Series:
    import random
    city_map = {
        "Midwest":   ["Detroit", "Chicago", "Columbus", "Indianapolis", "Cleveland"],
        "South":     ["Houston", "Charlotte", "Nashville", "Atlanta", "Memphis"],
        "Southwest": ["Phoenix", "Dallas", "San Antonio", "Denver", "Albuquerque"],
        "West":      ["Los Angeles", "Seattle", "San Jose", "Portland", "Sacramento"],
        "Northeast": ["Boston", "Philadelphia", "Pittsburgh", "Buffalo", "Baltimore"],
        "Southeast": ["Miami", "Tampa", "Raleigh", "Jacksonville", "Richmond"],
        "Mountain":  ["Salt Lake City", "Boise", "Tucson", "Spokane", "Helena"],
        "Plains":    ["Kansas City", "Omaha", "Wichita", "Sioux Falls", "Fargo"],
    }
    rng = random.Random(42)
    return pd.Series([rng.choice(city_map.get(r, ["Unknown"])) for r in regions])


@F.pandas_udf(StringType())
def gen_carrier(ids: pd.Series) -> pd.Series:
    carriers = ["FastFreight LLC", "GlobalShip Express", "PacificCargo Co",
                "AtlasLogistics", "SwiftTransit"]
    probs    = [0.30, 0.30, 0.20, 0.12, 0.08]   # Pareto: top-2 = 60%
    rng = np.random.default_rng(42)
    return pd.Series([rng.choice(carriers, p=probs) for _ in ids])


@F.pandas_udf(StringType())
def gen_tracking_number(ids: pd.Series) -> pd.Series:
    rng = np.random.default_rng(42)
    return pd.Series([f"TRK{rng.integers(1_000_000_000, 9_999_999_999)}" for _ in ids])


@F.pandas_udf(DoubleType())
def gen_freight_cost(ids: pd.Series) -> pd.Series:
    rng = np.random.default_rng(42)
    return pd.Series([round(float(rng.lognormal(4.5, 0.8)), 2) for _ in ids])


# ══════════════════════════════════════════════════════════════════════════════
# 1. SUPPLIERS
# ══════════════════════════════════════════════════════════════════════════════
print("── Generating suppliers ───────────────────────────────────")

COUNTRY_THRESHOLDS = [
    ("United States", 0.35), ("Germany", 0.50), ("Japan", 0.62), ("China", 0.72),
    ("South Korea", 0.78), ("Mexico", 0.84), ("Canada", 0.88), ("India", 0.91),
    ("Brazil", 0.94), ("United Kingdom", 0.96), ("France", 0.98), ("Italy", 1.00),
]

def _build_when_chain(col_name, thresholds):
    """Build a nested when/otherwise expression from (value, cumulative_threshold) pairs."""
    expr = None
    for val, thr in thresholds:
        cond = F.col(col_name) < thr
        expr = F.when(cond, val) if expr is None else expr.when(cond, val)
    return expr.otherwise(thresholds[-1][0])

country_expr      = _build_when_chain("_rc", COUNTRY_THRESHOLDS)
tier_expr         = (F.when(F.col("_rt") < 0.15, "Tier-1")
                      .when(F.col("_rt") < 0.55, "Tier-2")
                      .otherwise("Tier-3"))
payment_expr      = (F.when(F.col("_rp") < 0.10, 15)
                      .when(F.col("_rp") < 0.40, 30)
                      .when(F.col("_rp") < 0.70, 45)
                      .when(F.col("_rp") < 0.90, 60)
                      .otherwise(90))

suppliers_df = (
    spark.range(0, N_SUPPLIERS, numPartitions=4)
    .withColumn("_rt", F.rand(seed=1))
    .withColumn("_rc", F.rand(seed=2))
    .withColumn("_rp", F.rand(seed=3))
    .withColumn("supplier_id",       F.concat(F.lit("SUP-"), F.lpad(F.col("id").cast("string"), 5, "0")))
    .withColumn("supplier_name",     gen_supplier_name(F.col("id")))
    .withColumn("tier",              tier_expr)
    .withColumn("country",           country_expr)
    .withColumn("city",              gen_city_by_country(F.col("country")))
    .withColumn("contact_email",     gen_company_email(F.col("id")))
    .withColumn("reliability_score", gen_reliability_score(F.col("tier")))
    .withColumn("annual_revenue_usd", gen_annual_revenue(F.col("tier")))
    .withColumn("certifications",    gen_certifications(F.col("tier")))
    .withColumn("payment_terms_days", payment_expr)
    .withColumn("established_year",  (F.lit(1970) + (F.rand(seed=4) * 45).cast("int")).cast("int"))
    .drop("id", "_rt", "_rc", "_rp")
)

# Write to temp Delta (no .cache() on serverless)
suppliers_df.write.mode("overwrite").format("delta").saveAsTable(f"{TEMP_DB}.suppliers")
count = spark.table(f"{TEMP_DB}.suppliers").count()
print(f"  suppliers (temp Delta): {count:,} rows")

# Write Parquet to landing volume for pipeline ingestion
spark.table(f"{TEMP_DB}.suppliers").write.mode("overwrite").parquet(f"{VOLUME_PATH}/suppliers")
print(f"  Written: {VOLUME_PATH}/suppliers\n")


# ══════════════════════════════════════════════════════════════════════════════
# 2. PARTS
# ══════════════════════════════════════════════════════════════════════════════
print("── Generating parts ───────────────────────────────────────")

cat_expr = (F.when(F.col("_rc") < 0.30, "Raw Material")
             .when(F.col("_rc") < 0.70, "Sub-Assembly")
             .otherwise("Component"))

subcat_expr = (
    F.when(F.col("category") == "Raw Material",
           F.when(F.col("_rs") < 0.40, "Metal")
            .when(F.col("_rs") < 0.70, "Polymer")
            .otherwise("Composite"))
     .when(F.col("category") == "Sub-Assembly",
           F.when(F.col("_rs") < 0.50, "Powertrain")
            .when(F.col("_rs") < 0.75, "Chassis")
            .otherwise("Electronics"))
     .otherwise(
           F.when(F.col("_rs") < 0.40, "Mechanical")
            .when(F.col("_rs") < 0.70, "Electrical")
            .otherwise("Structural"))
)

uom_expr = (
    F.when(F.col("category") == "Raw Material",
           F.when(F.col("_rum") < 0.40, "KG")
            .when(F.col("_rum") < 0.70, "LB")
            .otherwise("M"))
     .otherwise("EA")
)

lead_expr = (
    F.when(F.col("category") == "Raw Material", (F.rand(seed=14) * 14  + 1).cast("int"))
     .when(F.col("category") == "Sub-Assembly", (F.rand(seed=15) * 60  + 14).cast("int"))
     .otherwise(                                 (F.rand(seed=16) * 30  + 3).cast("int"))
)

moq_expr = (
    F.when(F.col("category") == "Raw Material", (F.rand(seed=17) * 900 + 100).cast("int"))
     .when(F.col("category") == "Sub-Assembly", (F.rand(seed=18) * 9   + 1).cast("int"))
     .otherwise(                                 (F.rand(seed=19) * 49  + 1).cast("int"))
)

parts_df = (
    spark.range(0, N_PARTS, numPartitions=4)
    .withColumn("_rc",  F.rand(seed=5))
    .withColumn("_rs",  F.rand(seed=6))
    .withColumn("_rum", F.rand(seed=7))
    .withColumn("part_id",     F.concat(F.lit("PRT-"), F.lpad(F.col("id").cast("string"), 5, "0")))
    .withColumn("category",    cat_expr)
    .withColumn("subcategory", subcat_expr)
    .withColumn("part_name",   gen_part_name(
        F.concat(F.col("category"), F.lit("|"), F.col("id").cast("string"))))
    .withColumn("unit_cost_usd",   gen_unit_cost(F.col("category")))
    .withColumn("unit_of_measure", uom_expr)
    .withColumn("lead_time_days",  lead_expr)
    .withColumn("min_order_qty",   moq_expr)
    .withColumn("weight_kg",       F.round(F.rand(seed=20) * 99.9 + 0.1, 2))
    .withColumn("is_critical",     F.rand(seed=21) < 0.20)
    .drop("id", "_rc", "_rs", "_rum")
)

parts_df.write.mode("overwrite").format("delta").saveAsTable(f"{TEMP_DB}.parts")
count = spark.table(f"{TEMP_DB}.parts").count()
print(f"  parts (temp Delta): {count:,} rows")
spark.table(f"{TEMP_DB}.parts").write.mode("overwrite").parquet(f"{VOLUME_PATH}/parts")
print(f"  Written: {VOLUME_PATH}/parts\n")


# ══════════════════════════════════════════════════════════════════════════════
# 3. FACILITIES
# ══════════════════════════════════════════════════════════════════════════════
print("── Generating facilities ──────────────────────────────────")

REGION_THRESHOLDS = [
    ("Midwest", 0.125), ("South", 0.25), ("Southwest", 0.375), ("West", 0.50),
    ("Northeast", 0.625), ("Southeast", 0.75), ("Mountain", 0.875), ("Plains", 1.00),
]
region_expr = _build_when_chain("_rr", REGION_THRESHOLDS)

ftype_expr = (F.when(F.col("_rf") < 0.40, "Manufacturing")
               .when(F.col("_rf") < 0.70, "Assembly")
               .otherwise("Warehouse"))

capacity_expr = (
    F.when(F.col("facility_type") == "Warehouse",      (F.rand(seed=25) * 45_000 + 5_000).cast("int"))
     .when(F.col("facility_type") == "Manufacturing",  (F.rand(seed=26) * 15_000 + 2_000).cast("int"))
     .otherwise(                                        (F.rand(seed=27) * 8_000  + 1_000).cast("int"))
)

facilities_df = (
    spark.range(0, N_FACILITIES, numPartitions=2)
    .withColumn("_rf", F.rand(seed=22))
    .withColumn("_rr", F.rand(seed=23))
    .withColumn("facility_id",   F.concat(F.lit("FAC-"), F.lpad(F.col("id").cast("string"), 5, "0")))
    .withColumn("facility_type", ftype_expr)
    .withColumn("region",        region_expr)
    .withColumn("city",          gen_facility_city(F.col("region")))
    .withColumn("state",         F.lit("US"))
    .withColumn("country",       F.lit("United States"))
    .withColumn("facility_name",
        F.concat(F.col("city"), F.lit(" "), F.col("facility_type"), F.lit(" Facility")))
    .withColumn("capacity_units",         capacity_expr)
    .withColumn("current_utilization_pct", F.round(F.rand(seed=24) * 45 + 50, 1))
    .withColumn("manager_name",  gen_manager_name(F.col("id")))
    .withColumn("opened_year",   (F.lit(1980) + (F.rand(seed=28) * 40).cast("int")).cast("int"))
    .drop("id", "_rf", "_rr")
)

facilities_df.write.mode("overwrite").format("delta").saveAsTable(f"{TEMP_DB}.facilities")
count = spark.table(f"{TEMP_DB}.facilities").count()
print(f"  facilities (temp Delta): {count:,} rows")
spark.table(f"{TEMP_DB}.facilities").write.mode("overwrite").parquet(f"{VOLUME_PATH}/facilities")
print(f"  Written: {VOLUME_PATH}/facilities\n")


# ══════════════════════════════════════════════════════════════════════════════
# 4. BOM  (reads back from temp parts table — no .cache() on serverless)
# ══════════════════════════════════════════════════════════════════════════════
print("── Generating BOM ─────────────────────────────────────────")

# Only Sub-Assembly and Component parts can be BOM parents
assembly_parts = (
    spark.table(f"{TEMP_DB}.parts")
    .filter(F.col("category").isin("Sub-Assembly", "Component"))
    .select("part_id")
    .withColumn("p_idx", F.row_number().over(Window.orderBy("part_id")) - 1)
)

all_parts_indexed = (
    spark.table(f"{TEMP_DB}.parts")
    .select("part_id")
    .withColumn("c_idx", F.row_number().over(Window.orderBy("part_id")) - 1)
)

n_asm = assembly_parts.count()
n_all = all_parts_indexed.count()

bom_df = (
    # Generate slightly more than N_BOM to absorb self-reference drops
    spark.range(0, int(N_BOM * 1.15), numPartitions=4)
    .withColumn("p_idx", (F.col("id") % n_asm).cast("long"))
    .withColumn("c_idx", ((F.col("id") * 37 + 11) % n_all).cast("long"))
    .join(assembly_parts.withColumnRenamed("part_id", "parent_part_id"), "p_idx")
    .join(all_parts_indexed.withColumnRenamed("part_id", "child_part_id"), "c_idx")
    .filter(F.col("parent_part_id") != F.col("child_part_id"))
    .limit(N_BOM)
    .withColumn("bom_id",
        F.concat(F.lit("BOM-"), F.lpad(
            F.row_number().over(Window.orderBy("parent_part_id", "child_part_id")).cast("string"),
            5, "0")))
    .withColumn("quantity",         F.round(F.rand(seed=29) * 19 + 1, 0).cast("double"))
    .withColumn("unit_of_measure",  F.lit("EA"))
    .withColumn("effective_date",
        F.date_sub(F.current_date(), (F.rand(seed=30) * 730).cast("int")))
    .withColumn("is_active",        F.rand(seed=31) > 0.05)
    .select("bom_id", "parent_part_id", "child_part_id",
            "quantity", "unit_of_measure", "effective_date", "is_active")
)

bom_df.write.mode("overwrite").parquet(f"{VOLUME_PATH}/bom")
print(f"  Written: {VOLUME_PATH}/bom\n")


# ══════════════════════════════════════════════════════════════════════════════
# 5. PURCHASE ORDERS  (joins all three master temp tables)
# ══════════════════════════════════════════════════════════════════════════════
print("── Generating purchase orders ─────────────────────────────")

suppliers_idx = (
    spark.table(f"{TEMP_DB}.suppliers")
    .select("supplier_id")
    .withColumn("s_idx", F.row_number().over(Window.orderBy("supplier_id")) - 1)
)
parts_idx = (
    spark.table(f"{TEMP_DB}.parts")
    .select("part_id", "unit_cost_usd")
    .withColumn("p_idx", F.row_number().over(Window.orderBy("part_id")) - 1)
)
facilities_idx = (
    spark.table(f"{TEMP_DB}.facilities")
    .select("facility_id")
    .withColumn("f_idx", F.row_number().over(Window.orderBy("facility_id")) - 1)
)

n_sup = suppliers_idx.count()
n_prt = parts_idx.count()
n_fac = facilities_idx.count()

status_expr = (
    F.when(F.col("_rs") < 0.20, "Open")
     .when(F.col("_rs") < 0.50, "In-Transit")
     .when(F.col("_rs") < 0.85, "Received")
     .when(F.col("_rs") < 0.92, "Delayed")
     .otherwise("Cancelled")
)
priority_expr = (
    F.when(F.col("_rpr") < 0.10, "Critical")
     .when(F.col("_rpr") < 0.30, "High")
     .when(F.col("_rpr") < 0.70, "Medium")
     .otherwise("Low")
)
quantity_expr = (
    F.when(F.col("unit_cost_usd") < 50,   (F.col("_rq") * 490 + 10).cast("int"))
     .when(F.col("unit_cost_usd") < 500,  (F.col("_rq") * 90  + 10).cast("int"))
     .otherwise(                           (F.col("_rq") * 18  + 2).cast("int"))
)
lead_time_expr = (
    F.when(F.col("unit_cost_usd") < 50, (F.rand(seed=37) * 14 + 3).cast("int"))
     .otherwise(                         (F.rand(seed=38) * 60 + 7).cast("int"))
)

po_df = (
    spark.range(0, N_POS, numPartitions=8)
    .withColumn("_rs",  F.rand(seed=32))
    .withColumn("_rq",  F.rand(seed=33))
    .withColumn("_rd",  F.rand(seed=34))
    .withColumn("_rpr", F.rand(seed=35))
    .withColumn("s_idx", (F.col("id") % n_sup).cast("long"))
    .withColumn("p_idx", ((F.col("id") * 31 + 7) % n_prt).cast("long"))
    .withColumn("f_idx", ((F.col("id") * 11 + 3) % n_fac).cast("long"))
    .join(suppliers_idx, "s_idx")
    .join(parts_idx,     "p_idx")
    .join(facilities_idx, "f_idx")
    .withColumn("po_id",
        F.concat(F.lit("PO-"), F.lpad(F.col("id").cast("string"), 7, "0")))
    .withColumn("quantity",    quantity_expr)
    .withColumn("unit_price_usd",
        F.round(F.col("unit_cost_usd") * (1.0 + F.rand(seed=36) * 0.20), 2))
    .withColumn("total_value_usd",
        F.round(F.col("quantity").cast("double") * F.col("unit_price_usd"), 2))
    .withColumn("order_date",
        F.date_add(F.lit(str(START_DATE)).cast("date"), (F.col("_rd") * DATE_RANGE).cast("int")))
    .withColumn("lead_time_days", lead_time_expr)
    .withColumn("expected_delivery_date",
        F.date_add(F.col("order_date"), F.col("lead_time_days")))
    .withColumn("status",   status_expr)
    .withColumn("actual_delivery_date",
        F.when(F.col("status") == "Received",
            F.date_add(F.col("expected_delivery_date"), (F.rand(seed=39) * 10 - 2).cast("int")))
         .otherwise(F.lit(None).cast("date")))
    .withColumn("priority", priority_expr)
    .select("po_id", "facility_id", "supplier_id", "part_id",
            "quantity", "unit_price_usd", "total_value_usd",
            "order_date", "expected_delivery_date", "actual_delivery_date",
            "status", "priority")
)

# Write to temp Delta for shipments FK reference
po_df.write.mode("overwrite").format("delta").saveAsTable(f"{TEMP_DB}.purchase_orders")
count = spark.table(f"{TEMP_DB}.purchase_orders").count()
print(f"  purchase_orders (temp Delta): {count:,} rows")
spark.table(f"{TEMP_DB}.purchase_orders").write.mode("overwrite").parquet(f"{VOLUME_PATH}/purchase_orders")
print(f"  Written: {VOLUME_PATH}/purchase_orders\n")


# ══════════════════════════════════════════════════════════════════════════════
# 6. SHIPMENTS  (reads back from temp purchase_orders)
# ══════════════════════════════════════════════════════════════════════════════
print("── Generating shipments ───────────────────────────────────")

# Only POs with a physical movement get shipments (not Open or Cancelled)
eligible_pos = (
    spark.table(f"{TEMP_DB}.purchase_orders")
    .filter(F.col("status").isin("In-Transit", "Received", "Delayed"))
    .select("po_id", "supplier_id", "facility_id", "part_id",
            "quantity", "order_date", "expected_delivery_date")
)

shipment_status_expr = (
    F.when(F.col("_rss") < 0.04, "Lost")
     .when(F.col("_rss") < 0.10, "Delayed")
     .when(F.col("expected_arrival_date") <= F.current_date(), "Delivered")
     .otherwise("In-Transit")
)

shipments_df = (
    eligible_pos
    .withColumn("_rn", F.rand(seed=40))
    # 25% of POs get 2 partial shipments; rest get 1
    .withColumn("n_shipments",   F.when(F.col("_rn") < 0.25, 2).otherwise(1))
    .withColumn("ship_nums",     F.sequence(F.lit(1), F.col("n_shipments")))
    .withColumn("ship_num",      F.explode(F.col("ship_nums")))
    .withColumn("_rss",  F.rand(seed=41))
    .withColumn("quantity_shipped",
        F.when(F.col("n_shipments") == 2,
               (F.col("quantity") * (F.rand(seed=43) * 0.40 + 0.30)).cast("int"))
         .otherwise(F.col("quantity")))
    .withColumn("ship_date",
        F.date_add(F.col("order_date"), (F.rand(seed=44) * 5 + 1).cast("int")))
    .withColumn("transit_days",
        F.datediff(F.col("expected_delivery_date"), F.col("order_date")))
    .withColumn("expected_arrival_date",
        F.date_add(F.col("ship_date"), F.col("transit_days")))
    .withColumn("status", shipment_status_expr)
    .withColumn("delay_days",
        F.when(F.col("status") == "Delayed", (F.rand(seed=45) * 30 + 1).cast("int"))
         .otherwise(F.lit(0)))
    .withColumn("actual_arrival_date",
        F.when(F.col("status") == "Delivered",
               F.date_add(F.col("expected_arrival_date"), F.col("delay_days")))
         .otherwise(F.lit(None).cast("date")))
    .withColumn("shipment_id",
        F.concat(F.lit("SHP-"), F.lpad(
            F.row_number().over(Window.orderBy("po_id", "ship_num")).cast("string"),
            8, "0")))
    .withColumn("carrier",        gen_carrier(F.col("shipment_id")))
    .withColumn("tracking_number", gen_tracking_number(F.col("shipment_id")))
    .withColumn("freight_cost_usd", gen_freight_cost(F.col("shipment_id")))
    .select("shipment_id", "po_id", "supplier_id", "facility_id", "part_id",
            "quantity_shipped", "ship_date", "expected_arrival_date", "actual_arrival_date",
            "carrier", "tracking_number", "status", "delay_days", "freight_cost_usd")
)

shipments_df.write.mode("overwrite").parquet(f"{VOLUME_PATH}/shipments")
print(f"  Written: {VOLUME_PATH}/shipments\n")


# ══════════════════════════════════════════════════════════════════════════════
# Cleanup temp tables
# ══════════════════════════════════════════════════════════════════════════════
print("── Cleaning up temp tables ────────────────────────────────")
for tbl in ["suppliers", "parts", "facilities", "purchase_orders"]:
    spark.sql(f"DROP TABLE IF EXISTS {TEMP_DB}.{tbl}")
spark.sql(f"DROP SCHEMA IF EXISTS {CATALOG}.{TEMP_SCHEMA}")
print("  Temp tables dropped.\n")

print("=" * 60)
print("Data generation complete!")
print(f"Landing volume : {VOLUME_PATH}/")
print("Tables written : suppliers, parts, facilities, bom,")
print("                 purchase_orders, shipments")
print("")
print("Next step: databricks bundle deploy && databricks bundle run supply_chain_pipeline")
print("=" * 60)
