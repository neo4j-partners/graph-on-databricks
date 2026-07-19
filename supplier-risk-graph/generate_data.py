"""Synthetic data generator for the supplier-risk-graph demo.

Writes one CSV per node/table type and one per relationship type to data/, plus
ground_truth.json describing the two demo stories and the new dataset counts.

The demo is built from scratch around two graph-native stories:

- Story 1 (the hidden glassworks): five clean tier-1 bottle suppliers all feed
  the Americas business unit (BU-03) and are all fed by one middling-risk
  tier-2 supplier, Cascade Glassworks (SUP-901). No flat column surfaces
  Cascade; only betweenness over the supply network does.
- Story 2 (the clean payer in a bad group): Jade (CUST-904) is a spotless
  platinum account held 85% by Kestrel (CUST-901), which also controls two
  intermediate holdcos that own four defaulted companies outright, two levels
  further down. Nothing within two hops of Jade has failed, so no column and
  no proximity ranking ties Jade to the risk; only stake-weighted ownership
  propagation over the graph does.

The generator plants only the four column-findable classifications (Strategic
Account, Defaulted Customer, Delinquent Customer, High-Risk Supplier). The two
graph-native terms (Critical Supplier, Ownership Risk) are resolved live at
demo time and are never pre-planted.

Reproducible: the RNG seed is fixed, and all daysLate values are computed once at
generation time and stored. The as-of date defaults to today, so a run on a
different day shifts every date by that offset; pass --as-of YYYY-MM-DD to pin it
and get byte-identical output.

Run with: uv run generate_data.py
"""

from __future__ import annotations

import argparse
import csv
import itertools
import json
import math
import random
import subprocess
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

SEED = 42
# Snapshot ("as of") date. Defaults to today so a freshly generated dataset is
# always current; override with --as-of YYYY-MM-DD for a reproducible build. Only
# date arithmetic depends on it, never an RNG draw, so moving it shifts every
# issue/due/paid/opened date by the same offset while leaving all scores,
# amounts, exposures and cohorts identical. EVALUATED_AT, DEFAULTED_PERIOD and
# LAST_QUARTER_PERIODS are all finalized from it in main() after any override.
AS_OF = date.today()
EVALUATED_AT = f"{AS_OF.isoformat()}T00:00:00Z"
RULE_VERSION = "v1.0"
CURRENCY = "EUR"

# Background population sizes (protagonists are added on top of these).
N_CUSTOMERS = 500
N_SUPPLIERS = 150
N_PLATINUM = 60
N_GOLD = 140
N_STRATEGIC_BG = 6  # background platinum accounts also flagged Strategic, for realism
N_DELINQUENT = 15  # background customers planted to satisfy the Delinquent rule
# The supplier-to-supplier network is two cross-linked clusters bridged only by
# Cascade. SUP_WEB_CHORD_RATIO sets how many extra edges each cluster gets beyond
# the spanning tree that connects it, as a fraction of cluster size; chords are
# what give the cluster alternate routes, so no node inside it becomes a bridge.
# CASCADE_B_LINKS is how many cluster-B suppliers Cascade feeds directly, the
# other half of the bridge. SUP_HUB_DEGREE_MARGIN is how far the decoy hub's
# degree is pushed above the next-highest, so degree-ranking picks it, not
# Cascade.
SUP_WEB_CHORD_RATIO = 0.6
CASCADE_A_LINKS = 4
CASCADE_B_LINKS = 3
SUP_HUB_DEGREE_MARGIN = 4

# Ownership is a weighted multi-parent DAG, not a forest of groups. Filler
# groups are three levels deep and some subsidiaries are jointly held, so damage
# reaches an account by several routes at once and has to be summed rather than
# counted. Defaults are spread across those groups so no single group owns
# the story.
N_FILLER_GROUPS = 14
N_SCATTERED_PAIRS = 3  # defaulted parent-and-subsidiary pairs outside the decoys
JOINT_STAKE_RATIO = 0.25  # fraction of filler subsidiaries given a second owner

# Every ownership link outside the Kestrel group is a minority position, while
# Kestrel controls its subsidiaries outright (see KESTREL_GROUP_EDGES). This is
# the whole reason accumulation beats proximity: a default next door behind a
# nine percent stake transmits less than four defaults three levels away behind
# controlling ones. Widen this range and the nearest default starts winning
# again, which is exactly the degenerate case the demo exists to avoid.
FILLER_STAKE_RANGE = (0.03, 0.18)

SUPPLIER_RISK_THRESHOLD = 70  # riskScore on a 0-100 scale
LATE_DAYS_THRESHOLD = 60  # days

# THR-03, the Supply Concentration Threshold, as the governed parameter rather
# than as a score. A risk committee writes "review any supplier at or above the
# 95th percentile of supply betweenness"; it does not write a raw betweenness
# constant, which would mean nothing to it. The percentile is what RULE-05
# compares against, and it deliberately catches a cohort rather than a winner.
#
# This constant is fixed before any betweenness is computed and before the
# topology it will be applied to exists. That ordering is the point, and it is
# why this lands in its own commit ahead of the rebuild: "chosen before the run"
# has to be checkable from git history rather than asserted in a document. A
# threshold set after seeing the distribution is a post-hoc threshold no matter
# how it was derived.
#
# It does not move. If the protagonist fails to clear it, the topology is what
# gets fixed, under the two-iteration stopping rule in proposals/CONTRACT.md
# section 7.
# Widening it until something clears is the failure mode this comment exists to
# prevent.
#
# gds.py resolves this percentile against the computed distribution and writes
# the resulting cutoff onto the live THR-03 node, because that value cannot be
# known until betweenness has run. The resolved cutoff is an output. This is the
# input.
SUPPLY_CONCENTRATION_PERCENTILE = 95

# Filler risk scores are remapped from a uniform draw onto this right-skewed
# triangular shape (low, high, mode). Most filler suppliers land in a healthy
# band, the tail thins, and the ceiling caps near 80, so only a small cohort
# clears the 70 high-risk threshold and none reads an implausible 95. A flat
# 5-95 spread left a third of the base at or above 70 and a dozen near 95, which
# let plain Genie name scarier suppliers than the graph's own finding.
FILLER_RISK_LOW = 10
FILLER_RISK_HIGH = 76
FILLER_RISK_MODE = 33

DATA_DIR = Path(__file__).parent / "data"

# --- Protagonist ids (reserved high block, hand-named, excluded from draws) ---
CASCADE_ID = "SUP-901"
TIER1_IDS = ["SUP-902", "SUP-903", "SUP-904", "SUP-905", "SUP-906"]
PROTAGONIST_SUPPLIER_IDS = {CASCADE_ID, *TIER1_IDS}

KESTREL_ID = "CUST-901"  # top holding company
MARLIN_ID = "CUST-902"  # defaulted, under Harbour
PELICAN_ID = "CUST-903"  # defaulted, under Tern
JADE_ID = "CUST-904"  # the clean payer
HARBOUR_ID = "CUST-905"  # intermediate holdco under Kestrel
OSPREY_ID = "CUST-906"  # defaulted, under Harbour
TERN_ID = "CUST-907"  # intermediate holdco under Kestrel
HERON_ID = "CUST-908"  # defaulted, under Tern
HOLDCO_IDS = {KESTREL_ID, HARBOUR_ID, TERN_ID}  # no invoices, no findings
KESTREL_DEFAULT_IDS = [MARLIN_ID, PELICAN_ID, OSPREY_ID, HERON_ID]
PROTAGONIST_CUSTOMER_IDS = {
    KESTREL_ID, MARLIN_ID, PELICAN_ID, JADE_ID,
    HARBOUR_ID, OSPREY_ID, TERN_ID, HERON_ID,
}

# The Kestrel holding structure, hand-built so the Story 2 contrast is exact.
# Jade sits three hops from every one of the four defaults, so no proximity
# query finds her, but every stake on the path between them is a controlling
# one. That is what makes the weighted propagation land on Jade: the damage is
# far away but it arrives through wide pipes, and there are four of them.
KESTREL_GROUP_EDGES = [
    (JADE_ID, KESTREL_ID, 0.85),
    (HARBOUR_ID, KESTREL_ID, 0.70),
    (TERN_ID, KESTREL_ID, 0.65),
    (MARLIN_ID, HARBOUR_ID, 0.90),
    (OSPREY_ID, HARBOUR_ID, 0.80),
    (PELICAN_ID, TERN_ID, 0.85),
    (HERON_ID, TERN_ID, 0.75),
]

# Jade's total committed credit facility, and so her credit exposure. creditLimit
# carries one meaning across every customer (the committed facility, of which the
# open invoice balance is the drawn portion), so Jade's is simply pinned to the
# top of the platinum band that credit_limit_for() draws from.
JADE_CREDIT_FACILITY = 800_000

# Ceiling on drawn balance as a share of the committed facility, applied by
# fit_credit_facilities(). credit_limit_for() sizes the facility by segment before
# any invoice exists, so a customer that later accumulates a large open balance
# could end up drawn past its own limit. Eight were, on the dataset where this was
# found, and because the metric view exposes credit_utilization, Genie sorts by it
# and puts those rows at the top of the very answer the demo uses to show who is
# *missing*. A committed facility that does not cover the balance drawn against it
# is not a thing a credit team would have on its books, so it should not be a thing
# the generator emits.
#
# The ceiling is stricter than that failure: more rows get raised than were over
# 100%, because anything past 85% drawn reads as a stressed account and would rank
# just as misleadingly. Expect the run count to exceed the number actually broken.
MAX_CREDIT_UTILIZATION = 0.85

# The Story 2 defaults land in the last full calendar quarter before the as-of
# date, and the Story 1 exposure sums BU-03 revenue over that same quarter.
# Both are derived from AS_OF in main(); the placeholders here are replaced there.
DEFAULTED_PERIOD = ""
LAST_QUARTER_PERIODS: set[str] = set()

# --- Name vocabulary. Protagonist stems (Cascade, Harbor, Summit, Ironbridge,
# Clearwater, Aurora, Kestrel, Marlin, Pelican, Jade) are deliberately excluded
# so no filler name shares a stem with a protagonist. ---
NAME_STEMS = [
    "Alder", "Birch", "Cedar", "Delta", "Ember", "Fjord", "Granite", "Iris",
    "Juniper", "Lumen", "Meridian", "Northwind", "Orchid", "Pinnacle", "Quartz",
    "Ridgeline", "Tidal", "Umber", "Vector", "Willow", "Zephyr", "Atlas",
    "Basalt", "Cobalt", "Dune", "Elm", "Frost", "Glacier", "Hollow", "Indigo",
    "Jasper", "Kelvin", "Larch", "Maple", "Nimbus", "Onyx", "Poplar", "Quill",
    "Raven", "Sable", "Thistle", "Ochre", "Verdant", "Wren", "Yarrow", "Ash",
    "Bramble", "Coral", "Drift", "Fern", "Grove", "Hazel", "Linden", "Moss",
    "Reed", "Slate", "Terra", "Vale", "Wisp", "Cinder",
]
CUSTOMER_SUFFIXES = [
    "Beverages", "Retail", "Distribution", "Trading", "Hospitality",
    "Markets", "Foods", "Drinks Co", "Group", "Wholesale",
]
SUPPLIER_CATEGORIES = ["ingredients", "packaging", "logistics", "equipment", "services"]
# Subcategory vocabulary by category. "raw glass" is reserved for Cascade.
SUBCATEGORIES = {
    "ingredients": ["malt", "hops", "sugar", "flavorings"],
    "packaging": ["glass bottles", "cans", "caps", "labels"],
    "logistics": ["freight", "warehousing"],
    "equipment": ["brewing equipment", "cooling systems"],
    "services": ["consulting", "maintenance"],
}

# Which subcategories make up one commodity. A supply path counts as carrying a
# commodity only when every supplier on it trades in one of these, which is what
# scopes Supply Exposure to the material at risk instead of to bare
# reachability. It cannot be subcategory equality: the furnace at the raw end
# and the bottle maker at the finished end are different subcategories on the
# same chain.
#
# This grouping is an authored judgment, not instance data, so it belongs to the
# knowledge layer and never to Unity Catalog. The subcategory *values* are
# columns Run A has always been able to read, which the fairness rule requires.
# The grouping is the traversal filter, and handing it over hands over leg 3.
# guard.py enforces that: it fails if any comment or Genie instruction
# enumerates two or more members of one commodity.
#
# Seeded with the subcategories that exist today. The rebuild adds the
# intermediate glass tiers between the furnace and the bottle makers and extends
# this mapping with them. Written before those tiers exist on purpose, so the
# check is not authored against data that was just built to satisfy it.
COMMODITY_SUBCATEGORIES = {
    "glass": {"raw glass", "glass bottles"},
}

# Filler supplier name suffix derived from the supplier's subcategory, so a
# supplier's name always reads consistently with the specialty its subcategory
# column names (no "Cans Co" tagged glass bottles). Suffixes are distinct across
# subcategories, so no two subcategories can produce the same filler name. The
# glass-bottle filler suffix is "Glass Co": the protagonist bottle suffixes
# ("Glassworks", "Bottling Supply", "Bottles", "Containers") are reserved for
# Cascade and the five tier-1s and never appear here, so no filler string-matches
# into the glassworks story. Protagonist stems are excluded from NAME_STEMS too.
SUPPLIER_SUFFIX_BY_SUBCATEGORY = {
    "malt": "Malt Supply", "hops": "Hops Co", "sugar": "Sugar Co",
    "flavorings": "Flavor Co",
    "glass bottles": "Glass Co", "cans": "Canning", "caps": "Closures",
    "labels": "Labels",
    "freight": "Freight", "warehousing": "Warehousing",
    "brewing equipment": "Brewing Systems", "cooling systems": "Cooling Systems",
    "consulting": "Consulting", "maintenance": "Maintenance",
}

BUSINESS_UNITS = [
    {"id": "BU-01", "name": "Northern Europe", "region": "EMEA"},
    {"id": "BU-02", "name": "Southern Europe", "region": "EMEA"},
    {"id": "BU-03", "name": "Americas", "region": "AMER"},
    {"id": "BU-04", "name": "Asia Pacific", "region": "APAC"},
    {"id": "BU-05", "name": "Africa & Middle East", "region": "EMEA"},
]
BU_IDS = [bu["id"] for bu in BUSINESS_UNITS]

# --- The rebuilt knowledge layer (ontology). Entities and data sources are
# contiguous and paired by position; every governed concept earns its place in
# one of the two stories or the background contrast. ---
ENTITIES = [
    {"id": "ENT-01", "name": "Customer", "description": "A party that buys goods or services from the company."},
    {"id": "ENT-02", "name": "Supplier", "description": "A party that provides goods or services to the company."},
    {"id": "ENT-03", "name": "BusinessUnit", "description": "An organizational unit that recognizes revenue and owns customer relationships."},
    {"id": "ENT-04", "name": "Invoice", "description": "A billing document issued to a customer with a due date and settlement status."},
    {"id": "ENT-05", "name": "RevenueEntry", "description": "A recognized revenue amount for a business unit in a period."},
    {"id": "ENT-06", "name": "ComplianceFinding", "description": "An open or closed compliance issue raised against a customer."},
    {"id": "ENT-07", "name": "SupplyRelationship", "description": "A supplier-to-supplier supply link in the multi-tier supply network."},
]

DATA_SOURCES = [
    {"id": "DS-01", "name": "customers", "system": "Databricks Unity Catalog", "table": "supplier_risk.customers"},
    {"id": "DS-02", "name": "suppliers", "system": "Databricks Unity Catalog", "table": "supplier_risk.suppliers"},
    {"id": "DS-03", "name": "business_units", "system": "Databricks Unity Catalog", "table": "supplier_risk.business_units"},
    {"id": "DS-04", "name": "invoices", "system": "Databricks Unity Catalog", "table": "supplier_risk.invoices"},
    {"id": "DS-05", "name": "revenue_entries", "system": "Databricks Unity Catalog", "table": "supplier_risk.revenue_entries"},
    {"id": "DS-06", "name": "compliance_findings", "system": "Databricks Unity Catalog", "table": "supplier_risk.compliance_findings"},
    {"id": "DS-07", "name": "supply_relationships", "system": "Databricks Unity Catalog", "table": "supplier_risk.supply_relationships"},
    {"id": "DS-08", "name": "owned_by", "system": "Databricks Unity Catalog", "table": "supplier_risk.owned_by"},
]

BUSINESS_TERMS = [
    {"id": "TERM-01", "name": "Strategic Account", "definition": "A platinum customer flagged strategic by account management."},
    {"id": "TERM-02", "name": "Defaulted Customer", "definition": "A customer with a recorded default in the snapshot."},
    {"id": "TERM-03", "name": "Delinquent Customer", "definition": "A customer more than 60 days late on each of its last three invoices."},
    {"id": "TERM-04", "name": "High-Risk Supplier", "definition": "A supplier whose procurement risk score meets or exceeds the threshold."},
    {"id": "TERM-05", "name": "Critical Supplier", "definition": "A supplier that a disproportionate share of the multi-tier supply paths carrying a commodity into the business run through, leaving few alternatives around it. A Critical Supplier need not sell to a business unit directly, and often does not."},
    {"id": "TERM-06", "name": "Ownership Risk", "definition": "An active customer with a clean record of its own (it carries its own invoices and is neither defaulted nor delinquent) that absorbs more failure through its ownership stakes than any other trading customer. Risk propagates from every defaulted customer in the book along OWNED_BY edges in proportion to the size of each stake, so a small holding next to a failure transmits little and a controlling chain several levels long transmits a great deal. Defaulted members and invoice-less holding companies are excluded, so the clean operating account is the headline."},
]

BUSINESS_RULES = [
    {"id": "RULE-01", "name": "Strategic Account Rule",
     "expression": "customer.segment = 'platinum' AND flagged strategic",
     "description": "A platinum customer designated strategic by account management.",
     "threshold": ""},
    {"id": "RULE-02", "name": "Defaulted Customer Rule",
     "expression": "customer.defaultedPeriod is set",
     "description": "A default period is recorded on the customer.",
     "threshold": ""},
    {"id": "RULE-03", "name": "Delinquent Customer Rule",
     "expression": "all(last 3 invoices WHERE invoice.daysLate > 60)",
     "description": "More than 60 days late on each of the last three invoices.",
     "threshold": LATE_DAYS_THRESHOLD},
    {"id": "RULE-04", "name": "High-Risk Supplier Rule",
     "expression": "supplier.riskScore >= 70",
     "description": "Procurement risk score at or above the supplier risk threshold.",
     "threshold": SUPPLIER_RISK_THRESHOLD},
    {"id": "RULE-05", "name": "Critical Supplier Rule",
     "expression": "A supplier is a Critical Supplier when a disproportionate share of the supply paths carrying a commodity into a business unit run through it, leaving the unit few alternatives if that supplier stops. Measured as supply betweenness over the multi-tier SUPPLIES network (supplier -[:SUPPLIES]-> supplier, walked transitively), at or above the Supply Concentration Threshold.",
     "description": "The suppliers a business unit's commodity supply concentrates on, so that losing one leaves few alternatives. Read from precomputed supply betweenness and compared against the Supply Concentration Threshold, which catches a cohort rather than a single name.",
     "threshold": ""},
    {"id": "RULE-06", "name": "Ownership Risk Rule",
     "expression": "Ownership Risk applies to a clean-record customer with its own invoices (no defaultedPeriod, not Delinquent) whose stake-weighted propagated risk over OWNED_BY edges (customer -[:OWNED_BY]-> customer, walked transitively, weighted by ownershipPct) is >= the ownership contagion threshold, propagated from every Defaulted Customer in the book; excludes the defaulted members and any invoice-less holding company",
     "description": "Ownership Risk: an active, clean-record customer that absorbs more propagated failure through its ownership stakes than any other trading customer; read from precomputed weighted PageRank. Proximity to a default does not qualify an account on its own, since the size of the stake decides how much actually reaches it. The defaulted and delinquent members and the invoice-less holding companies are excluded so the clean operating account is the headline.",
     "threshold": ""},
    # The two exposure rules (C2). They carry the aggregation in the expression,
    # the same way RULE-04 carries "supplier.riskScore >= 70", so the measure a
    # term is MEASURED_BY traces down to real tables through EVALUATES/MAPS_TO.
    {"id": "RULE-07", "name": "Supply Exposure Rule",
     "expression": "sum(revenue_entries.amount) over the most recent full calendar quarter, for every business unit whose entire supply of the commodity at risk runs through the supplier, counting only paths on which every supplier trades in that commodity",
     "description": "The recognized revenue at risk behind a Critical Supplier. A business unit is exposed when every commodity-carrying supply path for the material at risk passes through that supplier, so reachability through suppliers trading in something else does not count. The graph decides which units are in scope and the lakehouse computes the amount.",
     "threshold": ""},
    {"id": "RULE-08", "name": "Credit Exposure Rule",
     "expression": "customers.creditLimit as the committed facility, with sum(invoices.amount WHERE status = 'open') as the drawn portion",
     "description": "The credit exposure on a customer is its total committed credit facility. The open invoice balance is the drawn portion of that facility, never an addition to it.",
     "threshold": ""},
]

POLICIES = [
    {"id": "POL-01", "name": "Credit Risk Policy", "type": "Credit"},
    {"id": "POL-02", "name": "Supply Chain Resilience Policy", "type": "Procurement"},
    {"id": "POL-03", "name": "Compliance (KYC) Policy", "type": "Compliance"},
]

THRESHOLDS = [
    {"id": "THR-01", "name": "Supplier Risk Threshold", "value": SUPPLIER_RISK_THRESHOLD, "currency": "", "basis": ""},
    {"id": "THR-02", "name": "Late Payment Threshold", "value": LATE_DAYS_THRESHOLD, "currency": "", "basis": ""},
    # The two graph-native thresholds are left empty here on purpose: gds.py
    # fills their `value` from the computed betweenness / PageRank distribution.
    #
    # `basis` is the other half of that split and is the reason the column
    # exists. THR-03's governed parameter is a percentile, pinned across
    # reseeds; the cutoff it resolves to moves on every build. One column cannot
    # honestly hold both, so `basis` carries the authored language and `value`
    # carries the output. RULE-05's expression ends "at or above the Supply
    # Concentration Threshold", so this is the text that answers the room's next
    # question in Beat 3, and answering it with a bare betweenness score is the
    # weakest possible moment for the strongest artifact leg 1 has.
    #
    # The suffix on the percentile is written out rather than computed because
    # contract section 7 makes the percentile immovable. If that ever changes,
    # this string is a place that has to change with it.
    {"id": "THR-03", "name": "Supply Concentration Threshold", "value": "", "currency": "",
     "basis": f"Review any supplier at or above the {SUPPLY_CONCENTRATION_PERCENTILE}th percentile of supply betweenness."},
    # THR-04's basis stays empty on purpose. Its honest text would describe a
    # cutoff placed between the protagonist and the runner-up, which is a fitted
    # value rather than a governed parameter, and contract section 8 bans
    # redesigning Story 2. Leaving it empty documents which thresholds are
    # governed and which are not.
    {"id": "THR-04", "name": "Ownership Contagion Threshold", "value": "", "currency": "", "basis": ""},
]

# term -> defining rule, stated explicitly. RULE-07/RULE-08 define measures rather
# than terms and are carried by MEASURE_DEFINED_BY below, so the two lists are no
# longer the same length. Pairing them positionally would silently mispair a
# seventh term with the Supply Exposure Rule, so the mapping is written out.
DEFINED_BY = [
    {"term_id": "TERM-01", "rule_id": "RULE-01"},
    {"term_id": "TERM-02", "rule_id": "RULE-02"},
    {"term_id": "TERM-03", "rule_id": "RULE-03"},
    {"term_id": "TERM-04", "rule_id": "RULE-04"},
    {"term_id": "TERM-05", "rule_id": "RULE-05"},
    {"term_id": "TERM-06", "rule_id": "RULE-06"},
]

# rule -> entities it reads.
EVALUATES = [
    {"rule_id": "RULE-01", "entity_id": "ENT-01"},  # Strategic Account -> Customer
    {"rule_id": "RULE-02", "entity_id": "ENT-01"},  # Defaulted Customer -> Customer
    {"rule_id": "RULE-03", "entity_id": "ENT-01"},  # Delinquent -> Customer
    {"rule_id": "RULE-03", "entity_id": "ENT-04"},  # Delinquent -> Invoice
    {"rule_id": "RULE-04", "entity_id": "ENT-02"},  # High-Risk Supplier -> Supplier
    {"rule_id": "RULE-05", "entity_id": "ENT-02"},  # Critical Supplier -> Supplier
    {"rule_id": "RULE-05", "entity_id": "ENT-07"},  # Critical Supplier -> SupplyRelationship
    {"rule_id": "RULE-05", "entity_id": "ENT-03"},  # Critical Supplier -> BusinessUnit
    {"rule_id": "RULE-06", "entity_id": "ENT-01"},  # Ownership Risk -> Customer
    {"rule_id": "RULE-07", "entity_id": "ENT-05"},  # Supply Exposure -> RevenueEntry
    {"rule_id": "RULE-07", "entity_id": "ENT-03"},  # Supply Exposure -> BusinessUnit
    {"rule_id": "RULE-08", "entity_id": "ENT-04"},  # Credit Exposure -> Invoice
    {"rule_id": "RULE-08", "entity_id": "ENT-01"},  # Credit Exposure -> Customer
]

CONSTRAINS = [
    {"policy_id": "POL-01", "entity_id": "ENT-01"},  # Credit Risk -> Customer
    {"policy_id": "POL-02", "entity_id": "ENT-02"},  # Supply Chain Resilience -> Supplier
    {"policy_id": "POL-03", "entity_id": "ENT-01"},  # Compliance (KYC) -> Customer
]

# A policy GOVERNS the rules that operationalize it. The Compliance (KYC) Policy
# carries no rule: it is operationalized through compliance findings, not a
# business rule, but stays for governance breadth.
GOVERNS = [
    {"policy_id": "POL-01", "rule_id": "RULE-03"},  # Credit Risk -> Delinquent
    {"policy_id": "POL-01", "rule_id": "RULE-02"},  # Credit Risk -> Defaulted
    {"policy_id": "POL-01", "rule_id": "RULE-06"},  # Credit Risk -> Ownership Risk
    {"policy_id": "POL-02", "rule_id": "RULE-04"},  # Supply Chain -> High-Risk Supplier
    {"policy_id": "POL-02", "rule_id": "RULE-05"},  # Supply Chain -> Critical Supplier
    {"policy_id": "POL-02", "rule_id": "RULE-07"},  # Supply Chain -> Supply Exposure
    {"policy_id": "POL-01", "rule_id": "RULE-08"},  # Credit Risk -> Credit Exposure
]

APPLIES_TO = [
    {"threshold_id": "THR-01", "term_id": "TERM-04"},  # Supplier Risk -> High-Risk Supplier
    {"threshold_id": "THR-02", "term_id": "TERM-03"},  # Late Payment -> Delinquent
    {"threshold_id": "THR-03", "term_id": "TERM-05"},  # Supply Concentration -> Critical Supplier
    {"threshold_id": "THR-04", "term_id": "TERM-06"},  # Ownership Contagion -> Ownership Risk
]

# Each logical entity maps 1:1 to the data source in the same position.
MAPS_TO = [
    {"entity_id": e["id"], "data_source_id": d["id"]}
    # strict=False on purpose: DATA_SOURCES carries one more row than ENTITIES,
    # the owned_by table, which is mapped explicitly below rather than positionally.
    for e, d in zip(ENTITIES, DATA_SOURCES, strict=False)
] + [
    # Ownership stakes are customer data, so the Customer entity carries a second
    # table. The positional zip above pairs the first seven entities with their
    # own tables; this one does not get an entity of its own.
    {"entity_id": "ENT-01", "data_source_id": "DS-08"},
]

# rule -> the threshold that governs it. APPLIES_TO runs Threshold -> BusinessTerm,
# which is unreachable walking outbound from the term, so a model standing on the
# rule has no forward path to the cutoff. This edge gives it one.
RULE_THRESHOLDS = [
    {"rule_id": "RULE-03", "threshold_id": "THR-02"},  # Delinquent -> Late Payment
    {"rule_id": "RULE-04", "threshold_id": "THR-01"},  # High-Risk Supplier -> Supplier Risk
    {"rule_id": "RULE-05", "threshold_id": "THR-03"},  # Critical Supplier -> Supply Concentration
    {"rule_id": "RULE-06", "threshold_id": "THR-04"},  # Ownership Risk -> Ownership Contagion
]

# The graph metrics behind the two graph-native terms. These name formally what
# the rule text only says in prose, so the governed vocabulary is reachable from
# the metric a result set carries (Supplier.betweenness, Customer.pagerank).
GRAPH_METRICS = [
    {"id": "GM-01", "name": "Supply Betweenness", "nodeLabel": "Supplier",
     "property": "betweenness", "algorithm": "gds.betweenness",
     "description": "Precomputed betweenness centrality over the supplier-to-supplier SUPPLIES network. Stored on Supplier.betweenness and governs the Critical Supplier term: the higher the score, the more multi-tier supply paths run through that one supplier."},
    {"id": "GM-02", "name": "Ownership Contagion", "nodeLabel": "Customer",
     "property": "pagerank", "algorithm": "weighted personalized gds.pageRank",
     "description": "Stake-weighted personalized PageRank seeded on every defaulted customer in the book and propagated over OWNED_BY, with ownershipPct as the relationship weight. Stored on Customer.pagerank and governs the Ownership Risk term: the higher the score, the more failure actually reaches that customer through the stakes held in it. Distance alone does not raise the score, because a token holding transmits almost nothing."},
]

# term -> the graph metric that detects it (how the risk is found).
SCORED_BY = [
    {"term_id": "TERM-05", "metric_id": "GM-01"},  # Critical Supplier -> betweenness
    {"term_id": "TERM-06", "metric_id": "GM-02"},  # Ownership Risk -> pagerank
]

# The governed measures (C2): what a risk is worth, as opposed to what it is.
# MEAS-02's wording must hold for every customer, not just Jade: creditLimit is
# the total committed facility on every row, and the open invoice balance is the
# portion of that facility already drawn, never an addition to it.
MEASURES = [
    {"id": "MEAS-01", "name": "Supply Exposure",
     "definition": "The recognized revenue that stops when a Critical Supplier stops: the most recent full quarter of recognized revenue for every business unit whose supply of the commodity at risk depends wholly on paths through that supplier. A path that does not carry the commodity creates no dependency and is excluded.",
     "grain": "business unit and fiscal quarter",
     "aggregation": "sum(revenue_entries.amount)"},
    {"id": "MEAS-02", "name": "Credit Exposure",
     "definition": "The total committed credit facility on a customer. The open invoice balance is the drawn portion of that facility, not an addition to it, so the exposure is the facility itself and the drawn portion is reported alongside it.",
     "grain": "customer",
     "aggregation": "customers.creditLimit as the committed facility, with sum(invoices.amount WHERE status = 'open') as the drawn portion"},
]

# term -> the measure that prices it (what the risk is worth).
MEASURED_BY = [
    {"term_id": "TERM-05", "measure_id": "MEAS-01"},  # Critical Supplier -> Supply Exposure
    {"term_id": "TERM-06", "measure_id": "MEAS-02"},  # Ownership Risk -> Credit Exposure
]

# measure -> defining rule. Kept in its own file because defined_by.csv is keyed
# term_id,rule_id; both load as the same DEFINED_BY relationship type.
MEASURE_DEFINED_BY = [
    {"measure_id": "MEAS-01", "rule_id": "RULE-07"},
    {"measure_id": "MEAS-02", "rule_id": "RULE-08"},
]


def last_full_quarter(as_of: date) -> tuple[str, set[str]]:
    """Label and month-period set of the last full calendar quarter before as_of.

    The current (in-progress) quarter is treated as not yet complete, so for an
    as-of date in Q3 the result is Q2: its label ("YYYY-Qn") and the set of its
    three "YYYY-MM" month periods.
    """
    quarter = (as_of.month - 1) // 3 + 1
    year = as_of.year
    quarter -= 1
    if quarter == 0:
        quarter, year = 4, year - 1
    start_month = (quarter - 1) * 3 + 1
    months = {f"{year}-{start_month + i:02d}" for i in range(3)}
    return f"{year}-Q{quarter}", months


def trailing_12_months(as_of: date) -> list[str]:
    """The twelve full "YYYY-MM" month periods ending the month before as_of."""
    periods = []
    year, month = as_of.year, as_of.month
    for _ in range(12):
        month -= 1
        if month == 0:
            year, month = year - 1, 12
        periods.append(f"{year}-{month:02d}")
    periods.reverse()
    return periods


def make_names(rng: random.Random, suffixes: list[str], count: int) -> list[str]:
    combos = [f"{stem} {suffix}" for stem in NAME_STEMS for suffix in suffixes]
    return rng.sample(combos, count)


def credit_limit_for(rng: random.Random, segment: str) -> int:
    """Credit line sized loosely by segment, rounded to a round thousand."""
    if segment == "platinum":
        return rng.randint(300, 800) * 1000
    if segment == "gold":
        return rng.randint(100, 400) * 1000
    return rng.randint(20, 150) * 1000


def fit_credit_facilities(customers: list[dict], invoices: list[dict]) -> int:
    """Raise any credit facility too small to cover the balance drawn against it.

    credit_limit_for() sizes the facility by segment before invoices exist, so it
    cannot know what a customer will end up owing. Where the open balance would
    exceed MAX_CREDIT_UTILIZATION of the facility, the facility is raised to the
    next round 10K that restores the ceiling. Only ever raises, so the segment
    banding still shows through, and skips Jade, whose facility is pinned.

    Returns the number of customers adjusted.
    """
    # Drawn means everything not yet settled, so an overdue invoice counts against
    # the facility exactly as an open one does. RULE-08 words the drawn portion as
    # status = 'open'; taking the superset here can only leave a customer further
    # under the ceiling than the rule reads it, never over.
    open_balance: dict[str, float] = {}
    for invoice in invoices:
        if invoice["status"] != "paid":
            open_balance[invoice["customerId"]] = (
                open_balance.get(invoice["customerId"], 0.0) + invoice["amount"]
            )

    adjusted = 0
    for customer in customers:
        if customer["id"] == JADE_ID:
            continue
        balance = open_balance.get(customer["id"], 0.0)
        if not balance:
            continue
        required = math.ceil(balance / MAX_CREDIT_UTILIZATION / 10_000) * 10_000
        if required > customer["creditLimit"]:
            customer["creditLimit"] = required
            adjusted += 1

    # The postcondition is the ceiling itself, not merely "drawn fits inside the
    # facility". Asserting the weaker form would pass on a 99%-utilized row, which
    # is exactly the implausible shape this function exists to remove. Jade is
    # skipped above but checked here, so her pinned facility has to clear the same
    # bar as everyone else's.
    for customer in customers:
        balance = open_balance.get(customer["id"], 0.0)
        assert balance <= customer["creditLimit"] * MAX_CREDIT_UTILIZATION, (
            f"{customer['id']} draws {balance} against a "
            f"{customer['creditLimit']} facility, above the "
            f"{MAX_CREDIT_UTILIZATION:.0%} utilization ceiling")
    return adjusted


def make_customers(rng: random.Random) -> tuple[list[dict], dict[str, list[str]]]:
    """Build the 500 background customers plus the planted background cohorts."""
    names = make_names(rng, CUSTOMER_SUFFIXES, N_CUSTOMERS)
    segments = (
        ["platinum"] * N_PLATINUM
        + ["gold"] * N_GOLD
        + ["silver"] * (N_CUSTOMERS - N_PLATINUM - N_GOLD)
    )
    rng.shuffle(segments)

    customers = []
    for i in range(N_CUSTOMERS):
        seg = segments[i]
        customers.append({
            "id": f"CUST-{i + 1:03d}",
            "name": names[i],
            "segment": seg,
            "profitabilityTrend": rng.choice(["improving", "stable", "declining"]),
            "churnRisk": rng.choice(["low", "medium", "high"]),
            "upsellScore": rng.randint(0, 100),
            "creditLimit": credit_limit_for(rng, seg),
            "defaultedPeriod": "",
        })

    platinum = [c["id"] for c in customers if c["segment"] == "platinum"]
    strategic_bg = rng.sample(platinum, N_STRATEGIC_BG)
    delinquent_pool = [c["id"] for c in customers if c["segment"] in ("gold", "silver")]
    delinquent_bg = rng.sample(delinquent_pool, N_DELINQUENT)

    cohorts = {"strategic_bg": strategic_bg, "delinquent_bg": delinquent_bg}
    return customers, cohorts


def make_protagonist_customers(rng: random.Random) -> list[dict]:
    """The Kestrel group. creditLimit for Jade is finalized later.

    Two intermediate holdcos (Harbour, Tern) sit between Kestrel and the four
    defaults, which is what puts Jade three hops from every failure instead of
    one hop from two. Ownership itself lives in owned_by.csv, not on these rows,
    because a subsidiary can have more than one owner.
    """
    def holdco(cid: str, name: str, upsell: int) -> dict:
        return {"id": cid, "name": name, "segment": "gold",
                "profitabilityTrend": "stable", "churnRisk": "low",
                "upsellScore": upsell, "creditLimit": credit_limit_for(rng, "gold"),
                "defaultedPeriod": ""}

    def defaulter(cid: str, name: str, upsell: int) -> dict:
        return {"id": cid, "name": name, "segment": "gold",
                "profitabilityTrend": "declining", "churnRisk": "high",
                "upsellScore": upsell, "creditLimit": credit_limit_for(rng, "gold"),
                "defaultedPeriod": DEFAULTED_PERIOD}

    return [
        holdco(KESTREL_ID, "Kestrel Holdings", 40),
        holdco(HARBOUR_ID, "Harbour Group Holdings", 35),
        holdco(TERN_ID, "Tern Capital Partners", 31),
        defaulter(MARLIN_ID, "Marlin Wholesale Drinks", 22),
        defaulter(PELICAN_ID, "Pelican Beverage Retail", 18),
        defaulter(OSPREY_ID, "Osprey Drinks Logistics", 20),
        defaulter(HERON_ID, "Heron Bottling Services", 16),
        {"id": JADE_ID, "name": "Jade Beverage Distribution", "segment": "platinum",
         "profitabilityTrend": "stable", "churnRisk": "low", "upsellScore": 88,
         "creditLimit": 0,  # finalized in main so exposure lands near 800K
         "defaultedPeriod": ""},
    ]


def skew_risk_score(uniform_draw: int) -> int:
    """Remap a uniform 5-95 draw onto a right-skewed risk distribution.

    Takes the value of a single ``rng.randint(5, 95)`` and reshapes it with a
    pure triangular inverse-CDF, consuming no randomness of its own. The caller
    still makes exactly one RNG draw per supplier, so the random stream and every
    downstream figure (both exposure totals, the delinquent cohort) stay
    byte-identical to the old uniform version; only the filler risk scores move.
    """
    low, high, mode = FILLER_RISK_LOW, FILLER_RISK_HIGH, FILLER_RISK_MODE
    p = (uniform_draw - 5) / 90  # the uniform draw's position in [0, 1]
    split = (mode - low) / (high - low)
    if p < split:
        value = low + math.sqrt(p * (high - low) * (mode - low))
    else:
        value = high - math.sqrt((1 - p) * (high - low) * (high - mode))
    return round(value)


def make_suppliers(rng: random.Random) -> list[dict]:
    """Build the 150 background suppliers plus the six Story 1 protagonists."""
    # One shuffled name pool per subcategory so each supplier's name suffix
    # matches its subcategory exactly. Suffixes are disjoint across subcategories,
    # so no full name repeats.
    name_pools = {
        subcat: [f"{stem} {suffix}" for stem in NAME_STEMS]
        for subcat, suffix in SUPPLIER_SUFFIX_BY_SUBCATEGORY.items()
    }
    for pool in name_pools.values():
        rng.shuffle(pool)

    suppliers = []
    for i in range(N_SUPPLIERS):
        category = rng.choice(SUPPLIER_CATEGORIES)
        subcategory = rng.choice(SUBCATEGORIES[category])
        suppliers.append({
            "id": f"SUP-{i + 1:03d}",
            # Name suffix derived from the subcategory, so name and column agree.
            "name": name_pools[subcategory].pop(),
            "category": category,
            "subcategory": subcategory,
            # A single uniform draw, reshaped into a right-skewed distribution so
            # a believable minority (not a third of the base) clears the risk
            # threshold.
            "riskScore": skew_risk_score(rng.randint(5, 95)),
        })

    # Cascade: middling risk (60-69), the hidden tier-2 raw-glass supplier.
    suppliers.append({"id": CASCADE_ID, "name": "Cascade Glassworks",
                      "category": "packaging", "subcategory": "raw glass",
                      "riskScore": rng.randint(60, 69)})
    # The five clean tier-1 bottle suppliers (below 40 so no score filter finds them).
    tier1_names = ["Harbor Bottling Supply", "Summit Glass Packaging",
                   "Ironbridge Containers", "Clearwater Bottles", "Aurora Packaging Co"]
    for sup_id, name in zip(TIER1_IDS, tier1_names, strict=True):
        suppliers.append({"id": sup_id, "name": name, "category": "packaging",
                          "subcategory": "glass bottles", "riskScore": rng.randint(10, 39)})
    return suppliers


def make_supplies(rng: random.Random, suppliers: list[dict]) -> list[dict]:
    """Supplier-to-business-unit edges (graph-only).

    Each background supplier serves 2-4 business units. The five tier-1 bottle
    suppliers each serve exactly the Americas (BU-03). Cascade serves no
    business unit directly: it is tier-2 and feeds the tier-1 suppliers instead.
    """
    supplies = []
    for supplier in suppliers:
        sid = supplier["id"]
        if sid == CASCADE_ID:
            continue
        if sid in TIER1_IDS:
            bus = ["BU-03"]
        else:
            # Only the five planted tier-1 suppliers may feed the Americas with
            # glass bottles, so plain Genie's beat-2 grouping of Americas
            # glass-bottle suppliers returns exactly those five and the
            # single-point-of-failure framing holds. Bar any background
            # glass-bottle supplier from BU-03.
            pool = BU_IDS
            if supplier["subcategory"] == "glass bottles":
                pool = [bu for bu in BU_IDS if bu != "BU-03"]
            bus = rng.sample(pool, rng.randint(2, 4))
        supplies.extend({"supplier_id": sid, "business_unit_id": bu} for bu in bus)
    return supplies


def make_supply_relationships(rng: random.Random, suppliers: list[dict]) -> list[dict]:
    """Supplier-to-supplier SUPPLIES edges: two webbed clusters, bridged by Cascade.

    The background splits into two clusters. Each is webbed internally with a
    spanning tree plus chords, so there are always several routes between any
    two suppliers inside a cluster and no node within one is a bottleneck. The
    five tier-1 bottle suppliers sit inside cluster A. Cascade is the only edge
    between the clusters: it feeds the tier-1s on the A side and a few suppliers
    on the B side. Every path from A to B therefore runs through Cascade, which
    is what gives it a betweenness in the thousands while its degree stays at 12
    (the five tier-1s, CASCADE_A_LINKS on the A side, CASCADE_B_LINKS on the B
    side).

    A decoy hub inside cluster A is then pushed to the highest degree in the
    network. It wins any count-the-connections ranking and loses betweenness
    badly, because the web around it routes traffic past it. That gap is the
    point of the whole demo: the most connected supplier is not the one the
    business cannot survive losing, and no aggregate over these rows finds
    Cascade. Only a shortest-path computation does.
    """
    background = [s for s in suppliers if s["id"] not in PROTAGONIST_SUPPLIER_IDS]
    pool = [s["id"] for s in background]
    rng.shuffle(pool)
    half = len(pool) // 2
    cluster_a = pool[:half] + list(TIER1_IDS)
    cluster_b = pool[half:]

    rels: list[dict] = []
    seen: set[tuple[str, str]] = set()

    def link(src: str, dst: str) -> bool:
        """Add one edge, skipping self-loops and duplicates in either direction."""
        if src == dst or (src, dst) in seen or (dst, src) in seen:
            return False
        seen.add((src, dst))
        rels.append({"fromSupplierId": src, "toSupplierId": dst})
        return True

    def web(cluster: list[str]) -> None:
        """Connect a cluster, then add chords so it has redundant routes."""
        shuffled = list(cluster)
        rng.shuffle(shuffled)
        for i in range(1, len(shuffled)):
            link(shuffled[rng.randrange(i)], shuffled[i])
        for _ in range(int(len(shuffled) * SUP_WEB_CHORD_RATIO)):
            a, b = rng.sample(shuffled, 2)
            link(a, b)

    web(cluster_a)
    web(cluster_b)

    # Cascade, the sole bridge. Raw material flows in from cluster B and finished
    # glass flows out to cluster A, so the B-side edges point at Cascade rather
    # than away from it. That direction matters: it keeps Cascade from being the
    # source of the whole network, so a recursive descendant count does not
    # single it out either. It also feeds a few cluster-A suppliers besides the
    # tier-1s, which stops any one tier-1 from becoming a second bridge.
    for tier1 in TIER1_IDS:
        link(CASCADE_ID, tier1)
    a_pool = [sid for sid in cluster_a if sid not in PROTAGONIST_SUPPLIER_IDS]
    for target in rng.sample(a_pool, CASCADE_A_LINKS):
        link(CASCADE_ID, target)
    for source in rng.sample(cluster_b, CASCADE_B_LINKS):
        link(source, CASCADE_ID)

    # The decoy hub: most connected supplier in the network, and nowhere near the
    # most critical. Chosen from cluster A among nodes already inside the web.
    degrees = Counter()
    for rel in rels:
        degrees[rel["fromSupplierId"]] += 1
        degrees[rel["toSupplierId"]] += 1
    hub = max((sid for sid in cluster_a if sid not in PROTAGONIST_SUPPLIER_IDS),
              key=lambda sid: (degrees[sid], sid))
    candidates = [sid for sid in cluster_a
                  if sid != hub and sid not in PROTAGONIST_SUPPLIER_IDS]
    rng.shuffle(candidates)
    # Subtly self-defeating when the runner-up is itself the chosen candidate:
    # linking hub to it raises BOTH degrees, so the gap does not grow that
    # iteration. The loop still converges because the candidate order is
    # shuffled, but it can also exhaust `candidates` without reaching the margin,
    # which is why check_story1 asserts the realized margin rather than trusting
    # this loop to have hit it.
    for candidate in candidates:
        others = max(n for sid, n in degrees.items() if sid != hub)
        if degrees[hub] >= others + SUP_HUB_DEGREE_MARGIN:
            break
        if link(hub, candidate):
            degrees[hub] += 1
            degrees[candidate] += 1
    return rels


def make_ownership(rng: random.Random, customers: list[dict]) -> list[dict]:
    """Weighted, multi-parent ownership. Returns the OWNED_BY edge rows.

    Every edge carries an ownershipPct, so influence is not "how many hops away"
    but "how much of you flows through." Filler groups run three levels deep and
    a quarter of their subsidiaries are jointly held, which means damage reaches
    an account by several routes at once and the routes have to be summed.

    Two decoys make the simple answers wrong, and both are planted here rather
    than tuned afterwards:

      * A proximity decoy sits one hop from a default, so hop-distance ranking
        picks it. The stake is two percent, so almost nothing actually reaches
        it.
      * A counting decoy is a group holding five defaults, more than Kestrel's
        four, so counting defaults per group picks it. Every stake in it is
        thin, so its clean members absorb very little.

    Jade wins on neither count and wins on weighted propagation, which is the
    only measure that reads the stakes.
    """
    by_id = {c["id"]: c for c in customers}
    edges: list[dict] = []

    def own(child: str, parent: str, pct: float) -> None:
        edges.append({"customer_id": child, "parent_customer_id": parent,
                      "ownershipPct": round(pct, 4)})

    for child, parent, pct in KESTREL_GROUP_EDGES:
        own(child, parent, pct)

    bg_ids = [c["id"] for c in customers if c["id"] not in PROTAGONIST_CUSTOMER_IDS]
    rng.shuffle(bg_ids)
    available = list(bg_ids)

    def take(n: int) -> list[str]:
        taken = available[:n]
        del available[:n]
        return taken

    # Filler groups: root -> 2-3 subsidiaries -> 1-2 sub-subsidiaries each.
    groups: list[dict] = []
    for index in range(N_FILLER_GROUPS):
        if len(available) < 10:
            break
        # The first group is the counting decoy and is built at full width, so
        # it has room for more defaults than Kestrel's four.
        widest = index < 2
        root = take(1)[0]
        mids = take(3 if widest else rng.randint(2, 3))
        leaves: list[str] = []
        kids_by_mid: dict[str, list[str]] = {}
        for mid in mids:
            own(mid, root, rng.uniform(*FILLER_STAKE_RANGE))
            kids = take(2 if widest else rng.randint(1, 2))
            for kid in kids:
                own(kid, mid, rng.uniform(*FILLER_STAKE_RANGE))
            kids_by_mid[mid] = kids
            leaves.extend(kids)
        # Joint stakes: a second owner elsewhere in the group, so the ownership
        # graph stops being a tree and damage can arrive by more than one route.
        for leaf in leaves:
            if len(mids) > 1 and rng.random() < JOINT_STAKE_RATIO:
                held_by = {e["parent_customer_id"] for e in edges
                           if e["customer_id"] == leaf}
                others = [m for m in mids if m not in held_by]
                if others:
                    own(leaf, rng.choice(others), rng.uniform(0.05, 0.30))
        groups.append({"root": root, "mids": mids, "kids": kids_by_mid})

    # The decoy plants below index groups[0], groups[1] and groups[2:2+N] by
    # position, but the loop above breaks early once `available` runs low. That is
    # unreachable at the current constants and an IndexError if N_CUSTOMERS drops
    # or N_FILLER_GROUPS rises, so it fails here with a message instead.
    required_groups = 2 + N_SCATTERED_PAIRS
    assert len(groups) >= required_groups, (
        f"ownership needs {required_groups} filler groups for the two decoys and "
        f"{N_SCATTERED_PAIRS} scattered pairs, but only {len(groups)} were built "
        f"from {len(bg_ids)} background customers; raise N_CUSTOMERS or lower "
        f"N_FILLER_GROUPS / N_SCATTERED_PAIRS")

    # Filler defaults are always planted as a parent-and-subsidiary pair, never
    # alone. A lone default has one owner and dumps everything it has onto that
    # one clean account, which would hand the top score to whoever happens to
    # sit next to it. Paired, the two absorb each other and only a token stake
    # leaks outward.
    def default_pair(group: dict, which: int) -> None:
        mid = group["mids"][which]
        by_id[mid]["defaultedPeriod"] = DEFAULTED_PERIOD
        by_id[group["kids"][mid][0]]["defaultedPeriod"] = DEFAULTED_PERIOD

    # The counting decoy: five defaults in one group, more than Kestrel's four.
    counting = groups[0]
    default_pair(counting, 0)
    default_pair(counting, 1)
    by_id[counting["root"]]["defaultedPeriod"] = DEFAULTED_PERIOD

    # The proximity decoy: the clean sibling of a defaulted pair, one hop from a
    # default, so hop-distance ranking picks it and weighted propagation does not.
    proximity = groups[1]
    default_pair(proximity, 0)

    # The rest, spread over the remaining groups so no one group owns the story.
    for group in groups[2:2 + N_SCATTERED_PAIRS]:
        default_pair(group, 0)

    # Now set the filler stakes from where the defaults actually landed. The
    # failed companies were closely held by each other, and outside investors
    # only ever took token positions in them. So a filler sitting next to a
    # default is holding three percent of it, and almost nothing reaches them,
    # while Kestrel's controlling stakes carry the damage all the way to Jade.
    #
    # This is the single most load-bearing choice in Story 2. Weighted
    # propagation splits a node's influence by RELATIVE stake, so what defeats
    # the proximity shortcut is not that filler stakes are small in absolute
    # terms, it is that they are small next to the stake the other owner holds.
    # Flatten these two ranges towards each other and the nearest default wins
    # again.
    defaulted_ids = {c["id"] for c in customers if c["defaultedPeriod"]}
    for edge in edges:
        pair = (edge["customer_id"], edge["parent_customer_id"])
        if any(cid in PROTAGONIST_CUSTOMER_IDS for cid in pair):
            continue  # the Kestrel group is hand-built above
        if all(cid in defaulted_ids for cid in pair):
            edge["ownershipPct"] = round(rng.uniform(0.80, 0.95), 4)
        elif any(cid in defaulted_ids for cid in pair):
            edge["ownershipPct"] = round(rng.uniform(0.02, 0.05), 4)

    # Nobody can be owned more than once over. The rewrite above is per-edge and
    # cannot see a child's other owners, so a jointly held subsidiary whose two
    # owners are BOTH defaulted takes the 0.80-0.95 branch twice and sums past
    # 100%. That happens in the counting decoy, where default_pair() defaults two
    # mids of one group: a leaf under mids[0] is defaulted by the same call, and
    # if its joint stake landed on mids[1] both of its edges qualify as
    # default-to-default.
    #
    # The fix is to scale an over-100% child's stakes down proportionally rather
    # than to exclude the both-owners-defaulted case from the fat branch.
    # Weighted propagation reads RELATIVE stake, so proportional scaling leaves
    # every ratio inside the child untouched and keeps default-to-default stakes
    # fat next to default-to-clean ones, which is the property that makes
    # accumulation beat proximity. Dropping such an edge to the thin branch would
    # leak a defaulted subsidiary's damage outward through the clean side of the
    # book and weaken exactly that contrast. Scaling is also a no-op on any child
    # already at or under 100%, so it only touches the broken rows.
    #
    # Truncating rather than rounding at four decimals guarantees the scaled
    # stakes cannot round back over 1.0.
    held: dict[str, float] = {}
    for edge in edges:
        held[edge["customer_id"]] = held.get(edge["customer_id"], 0.0) + edge["ownershipPct"]
    over = {cid: total for cid, total in held.items() if total > 1.0}
    for edge in edges:
        total = over.get(edge["customer_id"])
        if total is not None:
            edge["ownershipPct"] = math.floor(edge["ownershipPct"] / total * 10_000) / 10_000

    return edges


# --- Invoice builders. All share the customer_id / customerId key pair:
# customer_id (snake_case) feeds the has_invoice relationship CSV, customerId
# (camelCase) is the foreign key written to the invoices node/UC table. ---
def _invoice(inv_id: str, customer_id: str, amount: float, issue: date,
             due: date, paid: date | None, days_late: int, status: str) -> dict:
    return {
        "id": inv_id,
        "customer_id": customer_id,
        "customerId": customer_id,
        "amount": round(amount, 2),
        "currency": CURRENCY,
        "issueDate": issue.isoformat(),
        "dueDate": due.isoformat(),
        "paidDate": paid.isoformat() if paid else "",
        "daysLate": days_late,
        "status": status,
    }


def background_invoice(rng: random.Random, inv_id: str, customer_id: str) -> dict:
    """A believable invoice whose daysLate never exceeds the 60-day threshold.

    Keeping every background invoice at or below 60 days late guarantees no
    background customer accidentally satisfies the Delinquent rule; only the
    planted delinquent cohort does.
    """
    issue = AS_OF - timedelta(days=rng.randint(20, 380))
    due = issue + timedelta(days=30)
    amount = rng.uniform(800, 45_000)
    if due >= AS_OF:
        return _invoice(inv_id, customer_id, amount, issue, due, None, 0, "open")
    days_past = (AS_OF - due).days
    if days_past <= LATE_DAYS_THRESHOLD:
        if rng.random() < 0.35:
            return _invoice(inv_id, customer_id, amount, issue, due, None, days_past, "overdue")
        late = rng.randint(0, min(days_past, 30))
        return _invoice(inv_id, customer_id, amount, issue, due,
                        due + timedelta(days=late), late, "paid")
    late = rng.randint(0, 45)
    return _invoice(inv_id, customer_id, amount, issue, due,
                    due + timedelta(days=late), late, "paid")


def settled_invoice(rng: random.Random, inv_id: str, customer_id: str) -> dict:
    """An older invoice paid at most 20 days late; history filler for delinquents."""
    issue = AS_OF - timedelta(days=rng.randint(170, 380))
    due = issue + timedelta(days=30)
    late = rng.randint(0, 20)
    return _invoice(inv_id, customer_id, rng.uniform(800, 45_000), issue, due,
                    due + timedelta(days=late), late, "paid")


def overdue_invoice(rng: random.Random, inv_id: str, customer_id: str, days_late: int) -> dict:
    due = AS_OF - timedelta(days=days_late)
    return _invoice(inv_id, customer_id, rng.uniform(800, 45_000),
                    due - timedelta(days=30), due, None, days_late, "overdue")


def open_ontime_invoice(rng: random.Random, inv_id: str, customer_id: str) -> dict:
    """An open, not-yet-overdue invoice (dueDate in the future). Jade's clean balance."""
    issue = AS_OF - timedelta(days=rng.randint(0, 25))
    due = issue + timedelta(days=30)
    return _invoice(inv_id, customer_id, rng.uniform(40_000, 90_000), issue, due, None, 0, "open")


def make_invoices(rng: random.Random, customers: list[dict], delinquent: set[str]) -> list[dict]:
    invoices = []
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"INV-{counter:04d}"

    for customer in customers:
        cid = customer["id"]
        if cid in HOLDCO_IDS:
            continue  # holding companies trade through their subsidiaries
        if cid == JADE_ID:
            for _ in range(4):  # a few open, on-time invoices; carries the exposure
                invoices.append(open_ontime_invoice(rng, next_id(), cid))
            continue
        n = rng.randint(4, 8)
        if cid in delinquent:
            for _ in range(n - 3):
                invoices.append(settled_invoice(rng, next_id(), cid))
            for days_late in sorted(rng.sample(range(65, 121), 3), reverse=True):
                invoices.append(overdue_invoice(rng, next_id(), cid, days_late))
        else:
            for _ in range(n):
                invoices.append(background_invoice(rng, next_id(), cid))
    return invoices


def make_revenue_entries(rng: random.Random) -> list[dict]:
    """Monthly recognized revenue per business unit for the trailing 12 months.

    The Americas (BU-03) runs a consistently higher band every month, so no
    single quarter stands out as a planted spike on a revenue-over-time chart.
    Its last-full-quarter sum still lands inside the band check_exposure asserts.
    """
    periods = trailing_12_months(AS_OF)

    entries = []

    def add(bu_id: str, period: str, amount: float, reconciled: bool) -> None:
        entries.append({
            "id": f"REV-{len(entries) + 1:04d}",
            "business_unit_id": bu_id,
            "businessUnitId": bu_id,
            "period": period,
            "amount": round(amount, 2),
            "currency": CURRENCY,
            "reconciled": str(reconciled).lower(),
        })

    for bu in BUSINESS_UNITS:
        for period in periods:
            if bu["id"] == "BU-03":
                amount = rng.uniform(1_300_000, 1_500_000)
            else:
                amount = rng.uniform(200_000, 900_000)
            add(bu["id"], period, amount, rng.random() > 0.05)
    return entries


def make_findings(rng: random.Random, customers: list[dict]) -> list[dict]:
    """Ordinary compliance findings on a sample of background customers.

    Protagonists are excluded, so Jade and Kestrel keep clean records.
    """
    findings = []

    def add(customer_id: str, finding_type: str, status: str) -> None:
        opened = AS_OF - timedelta(days=rng.randint(15, 200))
        findings.append({
            "id": f"CF-{len(findings) + 1:03d}",
            "customer_id": customer_id,
            "customerId": customer_id,
            "type": finding_type,
            "status": status,
            "openedDate": opened.isoformat(),
        })

    bg_ids = [c["id"] for c in customers if c["id"] not in PROTAGONIST_CUSTOMER_IDS]
    for cid in rng.sample(bg_ids, 40):
        for _ in range(rng.randint(1, 2)):
            add(cid, rng.choice(["KYC", "AML", "sanctions"]), "open")
    for cid in rng.sample(bg_ids, 30):
        add(cid, rng.choice(["KYC", "AML", "sanctions"]), "closed")
    return findings


def add_payment_features(customers: list[dict], invoices: list[dict]) -> None:
    """Derive per-customer payment-behavior features from the generated invoices."""
    per_customer: dict[str, list[dict]] = {}
    for invoice in invoices:
        per_customer.setdefault(invoice["customer_id"], []).append(invoice)
    for customer in customers:
        rows = per_customer.get(customer["id"], [])
        if not rows:  # Kestrel has no invoices
            customer["avgDaysLate"] = 0.0
            customer["overdueShare"] = 0.0
            continue
        customer["avgDaysLate"] = round(sum(r["daysLate"] for r in rows) / len(rows), 1)
        customer["overdueShare"] = round(
            sum(1 for r in rows if r["status"] == "overdue") / len(rows), 2
        )


def compute_delinquent(customers: list[dict], invoices: list[dict]) -> list[str]:
    """Customers whose last three invoices (by dueDate) are each > 60 days late."""
    per_customer: dict[str, list[dict]] = {}
    for invoice in invoices:
        per_customer.setdefault(invoice["customer_id"], []).append(invoice)
    result = []
    for customer in customers:
        rows = per_customer.get(customer["id"], [])
        last_three = sorted(rows, key=lambda r: r["dueDate"], reverse=True)[:3]
        if len(last_three) == 3 and all(r["daysLate"] > LATE_DAYS_THRESHOLD for r in last_three):
            result.append(customer["id"])
    return result


# --- Offline self-checks. Each fails loudly if a plant invariant drifts. ---
def check_story1(suppliers: list[dict], supplies: list[dict],
                 supply_rels: list[dict]) -> None:
    by_id = {s["id"]: s for s in suppliers}
    bus_by_supplier: dict[str, set[str]] = {}
    for row in supplies:
        bus_by_supplier.setdefault(row["supplier_id"], set()).add(row["business_unit_id"])

    for tier1 in TIER1_IDS:
        assert "BU-03" in bus_by_supplier.get(tier1, set()), f"{tier1} must supply BU-03"
        assert by_id[tier1]["riskScore"] < 40, f"{tier1} riskScore must be clean (<40)"

    cascade_targets = {r["toSupplierId"] for r in supply_rels
                       if r["fromSupplierId"] == CASCADE_ID}
    assert set(TIER1_IDS) <= cascade_targets, "Cascade must supply every tier-1"
    assert 60 <= by_id[CASCADE_ID]["riskScore"] <= 69, "Cascade riskScore must be 60-69"

    # The five tier-1 suppliers must be the ONLY glass-bottle suppliers feeding
    # the Americas, so plain Genie's beat-2 grouping returns exactly five and no
    # background glass-bottle supplier offers an independent second glass source.
    americas_glass = {
        sid for sid, bus in bus_by_supplier.items()
        if "BU-03" in bus and by_id[sid]["subcategory"] == "glass bottles"
    }
    assert americas_glass == set(TIER1_IDS), (
        f"Americas glass-bottle suppliers must be exactly the five tier-1s, got {americas_glass}")
    assert len(americas_glass) == 5, \
        f"exactly five glass-bottle suppliers must serve BU-03, got {len(americas_glass)}"

    # Cascade supplies no business unit at all, so it owns zero rows in the
    # supplier_business_units bridge. This is the load-bearing invariant of the
    # whole demo: that bridge is what a region-scoped SQL query reads, so a single
    # row here would let plain Genie name Cascade and Story 1's honest miss would
    # quietly stop being a miss.
    assert CASCADE_ID not in bus_by_supplier, (
        f"Cascade must have zero supplier_business_units rows, got "
        f"{sorted(bus_by_supplier[CASCADE_ID])}")

    # ...and BU-03 therefore reaches Cascade only at the second hop, across a
    # supplier -> supplier edge. Cascade also feeds a few non-bottle cluster-A
    # suppliers that happen to serve BU-03, which is deliberate (it stops any one
    # tier-1 becoming a second bridge), so the exactness is asserted over the
    # glass-bottle route: the one the demo's question actually walks.
    bu03_suppliers = {sid for sid, bus in bus_by_supplier.items() if "BU-03" in bus}
    cascade_neighbors = {r["toSupplierId"] for r in supply_rels
                         if r["fromSupplierId"] == CASCADE_ID}
    cascade_neighbors |= {r["fromSupplierId"] for r in supply_rels
                          if r["toSupplierId"] == CASCADE_ID}
    bottle_route = {sid for sid in cascade_neighbors & bu03_suppliers
                    if by_id[sid]["subcategory"] == "glass bottles"}
    assert bottle_route == set(TIER1_IDS), (
        f"BU-03 must reach Cascade in exactly one bottle hop through the five "
        f"tier-1s, got {sorted(bottle_route)}")

    # Cascade must be the only link between the two clusters, so that removing it
    # splits the supplier network in two. This is the structural form of "strict
    # betweenness maximum" and the reason no aggregate over these rows finds it:
    # counting connections cannot see a cut vertex. Betweenness itself is a Phase
    # 2 computation; the invariant it depends on is asserted here.
    adjacency: dict[str, set[str]] = {}
    for rel in supply_rels:
        adjacency.setdefault(rel["fromSupplierId"], set()).add(rel["toSupplierId"])
        adjacency.setdefault(rel["toSupplierId"], set()).add(rel["fromSupplierId"])

    def reachable(start: str, blocked: str | None = None) -> set[str]:
        seen_nodes, stack = {start}, [start]
        while stack:
            for neighbor in adjacency.get(stack.pop(), ()):
                if neighbor != blocked and neighbor not in seen_nodes:
                    seen_nodes.add(neighbor)
                    stack.append(neighbor)
        return seen_nodes

    all_nodes = set(adjacency)
    assert reachable(CASCADE_ID) == all_nodes, \
        "the supplier network must be one connected component"
    without_cascade = reachable(TIER1_IDS[0], blocked=CASCADE_ID)
    assert len(without_cascade) < len(all_nodes) - 1, \
        "removing Cascade must split the supplier network, so it is the bridge"

    # Being *a* bridge is not enough: Cascade has to be the strict maximum on the
    # structural measure Story 1 turns on. The count of supplier pairs a node
    # separates is the CSV-checkable core of betweenness, since every path between
    # two separated nodes must pass through it. Any other supplier scoring as high
    # would give betweenness a rival and the demo a second answer. gds.py computes
    # the real betweenness in Neo4j, which cannot fail on a laptop; this is the
    # part of that result that can.
    def pairs_separated(node: str) -> int:
        remaining = all_nodes - {node}
        covered: set[str] = set()
        sizes = []
        for start in remaining:
            if start in covered:
                continue
            component = reachable(start, blocked=node)
            covered |= component
            sizes.append(len(component))
        return sum(a * b for a, b in itertools.combinations(sizes, 2))

    separated = {sid: pairs_separated(sid) for sid in all_nodes}
    ranked = sorted(separated, key=lambda sid: (separated[sid], sid), reverse=True)
    assert ranked[0] == CASCADE_ID, (
        f"{ranked[0]} separates more supplier pairs ({separated[ranked[0]]}) than "
        f"Cascade ({separated[CASCADE_ID]}), so betweenness would not name Cascade")
    assert separated[CASCADE_ID] > separated[ranked[1]], (
        f"Cascade must be the STRICT maximum, but {ranked[1]} ties it at "
        f"{separated[CASCADE_ID]}")

    # The most connected supplier must NOT be Cascade. This is the assertion the
    # whole demo rests on: if degree-ranking picked Cascade, a one-line GROUP BY
    # would answer Story 1 and the graph would be decoration.
    degrees = Counter()
    for rel in supply_rels:
        degrees[rel["fromSupplierId"]] += 1
        degrees[rel["toSupplierId"]] += 1
    top_by_degree = max(degrees, key=lambda sid: (degrees[sid], sid))
    assert top_by_degree != CASCADE_ID, (
        f"Cascade is the highest-degree supplier ({degrees[CASCADE_ID]}), so counting "
        f"connections would find it and the graph algorithm is not required")

    # ...and it must not merely lose, it must lose by the margin the decoy-hub
    # loop in make_supply_relationships was built to open. That loop exits
    # silently when it runs out of candidates before reaching the margin, so the
    # margin is only real if it is asserted. A one-degree lead would technically
    # satisfy the assert above while leaving the degree ranking a coin toss on
    # stage.
    runner_up = max(n for sid, n in degrees.items() if sid != top_by_degree)
    margin = degrees[top_by_degree] - runner_up
    assert margin >= SUP_HUB_DEGREE_MARGIN, (
        f"the decoy hub {top_by_degree} leads on degree by only {margin} "
        f"({degrees[top_by_degree]} vs {runner_up}), below the "
        f"{SUP_HUB_DEGREE_MARGIN} SUP_HUB_DEGREE_MARGIN the hub loop targets")


def check_story2(customers: list[dict], invoices: list[dict],
                 findings: list[dict], delinquent: set[str],
                 strategic_ids: set[str]) -> None:
    by_id = {c["id"]: c for c in customers}
    jade = by_id[JADE_ID]
    assert jade["segment"] == "platinum", "Jade must be platinum"
    assert JADE_ID in strategic_ids, "Jade must be classified Strategic Account"
    assert jade["defaultedPeriod"] == "", "Jade must not carry a defaultedPeriod"
    assert JADE_ID not in delinquent, "Jade must not be delinquent"
    jade_invoices = [i for i in invoices if i["customer_id"] == JADE_ID]
    assert jade_invoices and all(i["status"] == "open" for i in jade_invoices), \
        "Jade's invoices must all be open"
    assert not any(i["status"] == "overdue" for i in jade_invoices), \
        "Jade must have no overdue invoice"
    assert JADE_ID not in {f["customer_id"] for f in findings}, "Jade must have no finding"

    # The derived payment features have to agree with the invoices above. These
    # are the columns Genie actually reads, so they are what makes Story 2's miss
    # structural rather than lucky: every flat signal on Jade's own row is clean,
    # and only the ownership graph disagrees.
    assert jade["churnRisk"] == "low", \
        f"Jade must carry a low churnRisk, got {jade['churnRisk']}"
    assert jade["avgDaysLate"] == 0.0, \
        f"Jade must never have paid late, got avgDaysLate {jade['avgDaysLate']}"
    assert jade["overdueShare"] == 0.0, \
        f"Jade must carry no overdue share, got {jade['overdueShare']}"

    for defaulter in KESTREL_DEFAULT_IDS:
        assert by_id[defaulter]["defaultedPeriod"] == DEFAULTED_PERIOD, \
            f"{defaulter} must be defaulted"

    for holdco in HOLDCO_IDS:
        assert not any(i["customer_id"] == holdco for i in invoices), \
            f"{holdco} is a holding company and has no invoices"
        assert holdco not in {f["customer_id"] for f in findings}, \
            f"{holdco} is a holding company and has no findings"


def check_ownership(customers: list[dict], owned_by: list[dict]) -> None:
    """The two shortcuts that would let SQL answer Story 2 must both be dead.

    Jade must not be the nearest clean account to a default, and Jade's group
    must not hold the most defaults. If either were true, a hop count or a
    GROUP BY would find her and the weighted propagation would be decoration.
    """
    defaulted = {c["id"] for c in customers if c["defaultedPeriod"]}
    assert len(defaulted) >= 10, \
        f"defaults must be spread across the book, got {len(defaulted)}"

    # Landmine assert: every filler default is paired with another default, and
    # the pair holds each other far harder than any outsider holds either.
    #
    # A default with a single clean neighbour dumps all of its propagated mass
    # onto that one account regardless of stake size, which hands the top score
    # to whoever happens to sit next to it and defeats Story 2. The pairing is
    # what stops that, and until now nothing checked it: the plant lived in
    # `default_pair` and the reasoning lived in a comment.
    #
    # The band is asserted as a relationship rather than as numbers, per
    # contract section 9. Weighted propagation reads RELATIVE stake, so what
    # matters is not that a default-to-default stake is above some constant, it
    # is that it dominates every default-to-clean stake. Asserting the literal
    # 0.80-0.95 range would also fire spuriously on the over-100% proportional
    # scaling in the counting decoy, which is legitimate and documented.
    filler_defaults = defaulted - set(PROTAGONIST_CUSTOMER_IDS)
    dd_stakes, dc_stakes = [], []
    paired: set[str] = set()
    for edge in owned_by:
        child, parent = edge["customer_id"], edge["parent_customer_id"]
        if child in PROTAGONIST_CUSTOMER_IDS or parent in PROTAGONIST_CUSTOMER_IDS:
            continue
        stake = float(edge["ownershipPct"])
        if child in defaulted and parent in defaulted:
            dd_stakes.append(stake)
            paired.update({child, parent})
        elif child in defaulted or parent in defaulted:
            dc_stakes.append(stake)

    unpaired = sorted(filler_defaults - paired)
    assert not unpaired, (
        f"filler defaults with no defaulted partner: {unpaired}. A lone default "
        f"dumps its whole mass onto one clean neighbour, which is the proximity "
        f"shortcut Story 2 exists to defeat.")
    assert dd_stakes and dc_stakes, \
        "expected both default-to-default and default-to-clean filler stakes"
    assert min(dd_stakes) > max(dc_stakes), (
        f"the closely-held band must dominate the token band: weakest pair stake "
        f"{min(dd_stakes)} does not exceed strongest outside stake "
        f"{max(dc_stakes)}, so damage leaks outward and proximity wins")

    adjacency: dict[str, set[str]] = {}
    for edge in owned_by:
        adjacency.setdefault(edge["customer_id"], set()).add(edge["parent_customer_id"])
        adjacency.setdefault(edge["parent_customer_id"], set()).add(edge["customer_id"])

    # Hop distance from every clean account to the nearest default.
    distance: dict[str, int] = dict.fromkeys(defaulted, 0)
    frontier = list(defaulted)
    while frontier:
        nxt = []
        for cid in frontier:
            for neighbor in adjacency.get(cid, ()):
                if neighbor not in distance:
                    distance[neighbor] = distance[cid] + 1
                    nxt.append(neighbor)
        frontier = nxt
    jade_distance = distance.get(JADE_ID)
    assert jade_distance == 3, \
        f"Jade must sit three hops from the nearest default, got {jade_distance}"
    nearer = [cid for cid, d in distance.items()
              if cid not in defaulted and d < jade_distance]
    assert nearer, "some clean account must be nearer a default than Jade, or " \
        "hop distance alone would find her"

    # Defaults per connected ownership group.
    seen: set[str] = set()
    group_defaults: list[tuple[int, bool]] = []
    for start in adjacency:
        if start in seen:
            continue
        component, stack = {start}, [start]
        seen.add(start)
        while stack:
            for neighbor in adjacency.get(stack.pop(), ()):
                if neighbor not in component:
                    component.add(neighbor)
                    seen.add(neighbor)
                    stack.append(neighbor)
        group_defaults.append((len(component & defaulted), JADE_ID in component))
    jade_group = next(n for n, has_jade in group_defaults if has_jade)
    assert any(n > jade_group for n, has_jade in group_defaults if not has_jade), \
        f"Jade's group holds the most defaults ({jade_group}), so counting them " \
        f"per group would find her"


def check_exposure(revenue_entries: list[dict], bu03_last_quarter: float,
                   jade_exposure: float) -> None:
    """Story 1's revenue figure and Story 2's credit exposure.

    The BU-03 total is recomputed from revenue_entries here rather than taken on
    trust from the caller. Asserting the caller's number against a band only
    restates how it was drawn; recomputing it makes the check catch a caller that
    sums the wrong business unit, the wrong quarter, or the wrong column.
    """
    recomputed = round(
        sum(r["amount"] for r in revenue_entries
            if r["business_unit_id"] == "BU-03" and r["period"] in LAST_QUARTER_PERIODS), 2)
    assert recomputed == bu03_last_quarter, (
        f"BU-03 last-quarter revenue recomputes to {recomputed}, but the caller "
        f"reported {bu03_last_quarter}")
    assert 3_800_000 <= bu03_last_quarter <= 4_600_000, \
        f"BU-03 last-quarter revenue {bu03_last_quarter} outside the 3.8M-4.6M band"
    assert 750_000 <= jade_exposure <= 850_000, \
        f"Jade exposure {jade_exposure} outside the 800K band"


def check_referential(customers: list[dict], suppliers: list[dict],
                      supply_rels: list[dict], owned_by: list[dict]) -> None:
    customer_ids = {c["id"] for c in customers}
    supplier_ids = {s["id"] for s in suppliers}
    for c in customers:
        assert c["creditLimit"], f"{c['id']} must have a creditLimit"
    for edge in owned_by:
        assert edge["customer_id"] in customer_ids, f"unknown {edge['customer_id']}"
        assert edge["parent_customer_id"] in customer_ids, \
            f"unknown {edge['parent_customer_id']}"
        assert 0 < edge["ownershipPct"] <= 1, \
            f"{edge['customer_id']} stake {edge['ownershipPct']} out of range"
    # Per-edge range is not enough: a jointly held customer has several owner
    # edges, each individually legal, that can still sum past 100%. Nobody can be
    # owned more than once over, so check the child totals too.
    held: dict[str, float] = {}
    for edge in owned_by:
        held[edge["customer_id"]] = held.get(edge["customer_id"], 0.0) + edge["ownershipPct"]
    for cid, total in held.items():
        assert total <= 1.0, f"{cid} is owned {total:.4f}, more than once over"
    for s in suppliers:
        assert s["subcategory"], f"{s['id']} must have a subcategory"
    for rel in supply_rels:
        assert rel["fromSupplierId"] in supplier_ids, f"unknown {rel['fromSupplierId']}"
        assert rel["toSupplierId"] in supplier_ids, f"unknown {rel['toSupplierId']}"


def git_sha() -> str:
    """The commit this build came from, or a marker saying it is not knowable.

    Stamped into the build identity so that "which build did this transcript
    come from" is answerable from the artifact rather than from memory. A dirty
    tree gets the suffix, because a sha alone would claim a reproducibility the
    working tree does not have.
    """
    try:
        sha = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=True, cwd=DATA_DIR.parent,
        ).stdout.strip()
        dirty = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, check=True, cwd=DATA_DIR.parent,
        ).stdout.strip()
        return f"{sha}-dirty" if dirty else sha
    except (subprocess.CalledProcessError, FileNotFoundError):
        return "unknown"


def check_quarter(revenue_entries: list[dict], quarter_periods: set[str]) -> None:
    """The generated data covers the quarter it was shaped and asserted around.

    AS_OF is date.today() by design, so Beat 4's "most recent full quarter" is
    derived from the build date. This asserts the revenue actually spans that
    quarter, which catches a generator whose trailing window and whose quarter
    label have drifted apart.

    It is deliberately NOT the day-of check and cannot replace it. A build-time
    assert cannot catch a calendar quarter that rolls between building and
    demoing; only a comparison against the recorded build identity can, and that
    lives in the pre-flight. Conflating the two is how the gap survives.
    """
    covered = {row["period"] for row in revenue_entries}
    missing = quarter_periods - covered
    assert not missing, (
        f"revenue_entries does not cover the build's own quarter: missing "
        f"{sorted(missing)}. Beat 4 would sum a quarter the data does not hold.")


def check_ontology() -> None:
    """The knowledge layer must be walkable outbound from a BusinessTerm.

    Every path the demo relies on is asserted here: term to measure to rule to
    entity to table, term to metric, and rule to threshold.
    """
    rule_ids = {r["id"] for r in BUSINESS_RULES}
    entity_ids = {e["id"] for e in ENTITIES}
    term_ids = {t["id"] for t in BUSINESS_TERMS}
    measure_ids = {m["id"] for m in MEASURES}
    metric_ids = {m["id"] for m in GRAPH_METRICS}
    threshold_ids = {t["id"] for t in THRESHOLDS}
    mapped_entities = {m["entity_id"] for m in MAPS_TO}
    evaluated: dict[str, set[str]] = {}
    for row in EVALUATES:
        evaluated.setdefault(row["rule_id"], set()).add(row["entity_id"])

    # Every measure resolves to exactly one rule, and that rule exists.
    measure_rule = {}
    for row in MEASURE_DEFINED_BY:
        assert row["measure_id"] in measure_ids, f"unknown measure {row['measure_id']}"
        assert row["rule_id"] in rule_ids, f"unknown rule {row['rule_id']}"
        assert row["measure_id"] not in measure_rule, \
            f"{row['measure_id']} defined by more than one rule"
        measure_rule[row["measure_id"]] = row["rule_id"]
    assert set(measure_rule) == measure_ids, \
        f"measures with no defining rule: {sorted(measure_ids - set(measure_rule))}"

    # Every measure rule reaches at least one entity that MAPS_TO a data source.
    for measure_id, rule_id in measure_rule.items():
        entities = evaluated.get(rule_id, set())
        assert entities <= entity_ids, f"{rule_id} evaluates an unknown entity"
        grounded = entities & mapped_entities
        assert grounded, f"{measure_id} -> {rule_id} reaches no mapped data source"

    # Both graph-native terms carry exactly one metric and exactly one measure.
    for term_id in ("TERM-05", "TERM-06"):
        metrics = [r for r in SCORED_BY if r["term_id"] == term_id]
        measures = [r for r in MEASURED_BY if r["term_id"] == term_id]
        assert len(metrics) == 1, f"{term_id} must have exactly one SCORED_BY metric"
        assert len(measures) == 1, f"{term_id} must have exactly one MEASURED_BY measure"
        assert metrics[0]["metric_id"] in metric_ids, "unknown graph metric"
        assert measures[0]["measure_id"] in measure_ids, "unknown measure"
    assert {r["term_id"] for r in SCORED_BY} | {r["term_id"] for r in MEASURED_BY} <= term_ids, \
        "SCORED_BY / MEASURED_BY reference an unknown term"

    # Every term resolves to exactly one rule, and no term borrows a measure rule.
    # DEFINED_BY is written out by hand, so this is what catches a slipped pairing.
    measure_rule_ids = set(measure_rule.values())
    term_rule = {}
    for row in DEFINED_BY:
        assert row["term_id"] in term_ids, f"unknown term {row['term_id']}"
        assert row["rule_id"] in rule_ids, f"unknown rule {row['rule_id']}"
        assert row["term_id"] not in term_rule, \
            f"{row['term_id']} defined by more than one rule"
        assert row["rule_id"] not in measure_rule_ids, \
            f"{row['term_id']} is defined by measure rule {row['rule_id']}"
        term_rule[row["term_id"]] = row["rule_id"]
    assert set(term_rule) == term_ids, \
        f"terms with no defining rule: {sorted(term_ids - set(term_rule))}"
    assert len(set(term_rule.values())) == len(term_rule), \
        "two terms share a defining rule"

    # Every rule a threshold governs has a forward rule -> threshold row, and
    # every rule-threshold row points at a real rule and a real threshold.
    # term_rule is the dict validated above, reused rather than rebuilt.
    rule_threshold = {row["rule_id"]: row["threshold_id"] for row in RULE_THRESHOLDS}
    for row in RULE_THRESHOLDS:
        assert row["rule_id"] in rule_ids, f"unknown rule {row['rule_id']}"
        assert row["threshold_id"] in threshold_ids, f"unknown threshold {row['threshold_id']}"
    for row in APPLIES_TO:
        rule_id = term_rule[row["term_id"]]
        assert rule_threshold.get(rule_id) == row["threshold_id"], (
            f"{rule_id} defines a term governed by {row['threshold_id']} but has "
            f"no matching rule_thresholds row")

    # Term-name salience: each graph-native rule must name its own term.
    by_rule = {r["id"]: r for r in BUSINESS_RULES}
    for term in BUSINESS_TERMS:
        if term["id"] not in ("TERM-05", "TERM-06"):
            continue
        rule = by_rule[term_rule[term["id"]]]
        assert term["name"] in rule["expression"], \
            f"{rule['id']} expression must name '{term['name']}'"
    assert "SUPPLIES" in by_rule["RULE-05"]["expression"], \
        "RULE-05 must name the SUPPLIES relationship type"
    assert "OWNED_BY" in by_rule["RULE-06"]["expression"], \
        "RULE-06 must name the OWNED_BY relationship type"

    # Every new rule is governed by a policy, so the governance shape stays whole.
    governed = {row["rule_id"] for row in GOVERNS}
    for rule_id in ("RULE-07", "RULE-08"):
        assert rule_id in governed, f"{rule_id} is governed by no policy"

    # Path depth from a term to its tables, which is not the same on both paths.
    # A classification walks term -> rule -> entity -> table, three edges. A
    # measure walks term -> measure -> rule -> entity -> table, four, because a
    # measure is defined by its own rule rather than by the term's. Beat 4 of the
    # demo depends on the longer one, so a depth-bounded discovery probe that
    # stops at three reaches the RevenueEntry entity and never reaches
    # revenue_entries, the only table with money in it. Verified live against the
    # graph: at depth 3 from 'Critical Supplier' every table arrives except that
    # one. Nothing else in this function forces the fourth hop to stay
    # traversable, and nothing forces it to lead anywhere new, so both are
    # asserted here and a future reshaping fails the build instead of the stage.
    maps_to: dict[str, set[str]] = {}
    for row in MAPS_TO:
        maps_to.setdefault(row["entity_id"], set()).add(row["data_source_id"])

    def tables_reached(rule_id: str) -> set[str]:
        """The data sources a rule reaches, two edges on via EVALUATES/MAPS_TO."""
        return {
            ds for ent in evaluated.get(rule_id, set()) for ds in maps_to.get(ent, ())
        }

    for term_id, rule_id in term_rule.items():
        assert tables_reached(rule_id), (
            f"{term_id} reaches no table three edges out "
            f"(term -> rule -> entity -> table)")

    for row in MEASURED_BY:
        term_id, measure_id = row["term_id"], row["measure_id"]
        measure_tables = tables_reached(measure_rule[measure_id])
        assert measure_tables, (
            f"{term_id} -> {measure_id} reaches no table four edges out "
            f"(term -> measure -> rule -> entity -> table)")
        # The fourth hop has to buy something. If the measure's rule reached only
        # tables the term's own rule already reaches, MEASURED_BY would be
        # decoration and Beat 4 would have nowhere to walk that Beat 3 had not
        # already been.
        assert measure_tables - tables_reached(term_rule[term_id]), (
            f"{term_id} -> {measure_id} reaches no table beyond the ones "
            f"{term_rule[term_id]} already reaches; the MEASURED_BY hop buys "
            f"nothing and the exposure beat has nothing to resolve")


def write_csv(name: str, fieldnames: list[str], rows: list[dict]) -> None:
    path = DATA_DIR / name
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {name}: {len(rows)} rows")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate the supplier-risk-graph demo data.")
    parser.add_argument(
        "--as-of", type=date.fromisoformat, default=None, metavar="YYYY-MM-DD",
        help="Snapshot date; defaults to today. Pin it for a reproducible build.")
    args = parser.parse_args()

    global AS_OF, EVALUATED_AT, DEFAULTED_PERIOD, LAST_QUARTER_PERIODS
    AS_OF = args.as_of or date.today()
    EVALUATED_AT = f"{AS_OF.isoformat()}T00:00:00Z"
    DEFAULTED_PERIOD, LAST_QUARTER_PERIODS = last_full_quarter(AS_OF)

    rng = random.Random(SEED)
    DATA_DIR.mkdir(exist_ok=True)

    background, cohorts = make_customers(rng)
    customers = background + make_protagonist_customers(rng)
    suppliers = make_suppliers(rng)

    # Business unit per customer (foreign key on the node + belongs_to edge).
    belongs_to = [
        {"customer_id": c["id"], "business_unit_id": rng.choice(BUSINESS_UNITS)["id"]}
        for c in customers
    ]
    bu_by_customer = {b["customer_id"]: b["business_unit_id"] for b in belongs_to}
    for c in customers:
        c["businessUnitId"] = bu_by_customer[c["id"]]

    owned_by = make_ownership(rng, customers)

    delinquent_set = set(cohorts["delinquent_bg"])
    invoices = make_invoices(rng, customers, delinquent_set)

    # Finalize Jade's credit line. creditLimit means the same thing on every row:
    # the total committed facility. Jade's is pinned to the top of the platinum
    # band so her exposure is the headline 800K, with her open invoice balance
    # drawn inside that facility rather than added on top of it.
    jade_open_balance = round(
        sum(i["amount"] for i in invoices if i["customer_id"] == JADE_ID), 2)
    jade = next(c for c in customers if c["id"] == JADE_ID)
    jade["creditLimit"] = JADE_CREDIT_FACILITY
    assert jade_open_balance < jade["creditLimit"], (
        f"Jade's drawn balance {jade_open_balance} must sit inside her "
        f"{jade['creditLimit']} committed facility")

    # The same rule Jade's assert states, applied to everyone else: a committed
    # facility has to cover the balance drawn against it.
    refitted = fit_credit_facilities(customers, invoices)
    if refitted:
        print(f"Raised {refitted} credit facilities to cover their drawn balance.")

    revenue_entries = make_revenue_entries(rng)
    findings = make_findings(rng, customers)
    add_payment_features(customers, invoices)

    supplies = make_supplies(rng, suppliers)
    supply_rels = make_supply_relationships(rng, suppliers)

    owned_by_edges = len(owned_by)

    # Recompute the delinquent cohort from the data (must equal the plant).
    delinquent = compute_delinquent(customers, invoices)
    assert set(delinquent) == delinquent_set, "delinquent cohort drifted from the plant"
    high_risk_suppliers = [
        s["id"] for s in suppliers
        if s["id"] not in PROTAGONIST_SUPPLIER_IDS and s["riskScore"] >= SUPPLIER_RISK_THRESHOLD
    ]
    strategic_accounts = [JADE_ID] + cohorts["strategic_bg"]
    defaulted_customers = sorted(c["id"] for c in customers if c["defaultedPeriod"])

    # Pre-planted classifications: only the four column-findable terms. The two
    # graph-native terms (Critical Supplier, Ownership Risk) resolve live and
    # are never planted here.
    classified_as = []
    for cid in strategic_accounts:
        classified_as.append({
            "entity_id": cid, "entity_label": "Customer", "term_id": "TERM-01",
            "reason": "platinum segment and flagged strategic by account management",
            "evaluatedAt": EVALUATED_AT, "ruleVersion": RULE_VERSION})
    for cid in defaulted_customers:
        classified_as.append({
            "entity_id": cid, "entity_label": "Customer", "term_id": "TERM-02",
            "reason": "default period recorded in the snapshot",
            "evaluatedAt": EVALUATED_AT, "ruleVersion": RULE_VERSION})
    for cid in delinquent:
        classified_as.append({
            "entity_id": cid, "entity_label": "Customer", "term_id": "TERM-03",
            "reason": "each of the last three invoices more than 60 days late",
            "evaluatedAt": EVALUATED_AT, "ruleVersion": RULE_VERSION})
    for sid in high_risk_suppliers:
        classified_as.append({
            "entity_id": sid, "entity_label": "Supplier", "term_id": "TERM-04",
            "reason": "risk score at or above the supplier risk threshold",
            "evaluatedAt": EVALUATED_AT, "ruleVersion": RULE_VERSION})

    realized_as = (
        [{"entity_id": "ENT-01", "instance_id": c["id"], "instance_label": "Customer"} for c in customers]
        + [{"entity_id": "ENT-02", "instance_id": s["id"], "instance_label": "Supplier"} for s in suppliers]
        + [{"entity_id": "ENT-03", "instance_id": bu["id"], "instance_label": "BusinessUnit"} for bu in BUSINESS_UNITS]
        + [{"entity_id": "ENT-04", "instance_id": i["id"], "instance_label": "Invoice"} for i in invoices]
        + [{"entity_id": "ENT-05", "instance_id": r["id"], "instance_label": "RevenueEntry"} for r in revenue_entries]
        + [{"entity_id": "ENT-06", "instance_id": f["id"], "instance_label": "ComplianceFinding"} for f in findings]
    )

    bu03_last_quarter = round(
        sum(r["amount"] for r in revenue_entries
            if r["business_unit_id"] == "BU-03" and r["period"] in LAST_QUARTER_PERIODS), 2)
    # Credit exposure is the committed facility itself (MEAS-02). The open
    # balance is the drawn portion of it, so it is reported, never added.
    jade_exposure = round(float(jade["creditLimit"]), 2)

    # Self-checks (offline, fail loud).
    strategic_ids = {row["entity_id"] for row in classified_as if row["term_id"] == "TERM-01"}
    check_story1(suppliers, supplies, supply_rels)
    check_story2(customers, invoices, findings, delinquent_set, strategic_ids)
    check_ownership(customers, owned_by)
    check_exposure(revenue_entries, bu03_last_quarter, jade_exposure)
    check_referential(customers, suppliers, supply_rels, owned_by)
    check_ontology()
    check_quarter(revenue_entries, LAST_QUARTER_PERIODS)

    print("Instance node / table CSVs:")
    write_csv("customers.csv",
              ["id", "businessUnitId", "name", "segment", "profitabilityTrend", "churnRisk",
               "upsellScore", "avgDaysLate", "overdueShare",
               "creditLimit", "defaultedPeriod"], customers)
    write_csv("suppliers.csv", ["id", "name", "category", "subcategory", "riskScore"], suppliers)
    write_csv("business_units.csv", ["id", "name", "region"], BUSINESS_UNITS)
    write_csv("invoices.csv",
              ["id", "customerId", "amount", "currency", "issueDate", "dueDate", "paidDate",
               "daysLate", "status"], invoices)
    write_csv("revenue_entries.csv",
              ["id", "businessUnitId", "period", "amount", "currency", "reconciled"], revenue_entries)
    write_csv("compliance_findings.csv",
              ["id", "customerId", "type", "status", "openedDate"], findings)
    write_csv("supply_relationships.csv", ["fromSupplierId", "toSupplierId"], supply_rels)
    write_csv("owned_by.csv",
              ["customer_id", "parent_customer_id", "ownershipPct"], owned_by)

    print("Knowledge-layer CSVs:")
    write_csv("entities.csv", ["id", "name", "description"], ENTITIES)
    write_csv("business_terms.csv", ["id", "name", "definition"], BUSINESS_TERMS)
    write_csv("business_rules.csv",
              ["id", "name", "expression", "description", "threshold"], BUSINESS_RULES)
    write_csv("policies.csv", ["id", "name", "type"], POLICIES)
    write_csv("thresholds.csv", ["id", "name", "value", "currency", "basis"], THRESHOLDS)
    write_csv("data_sources.csv", ["id", "name", "system", "table"], DATA_SOURCES)
    write_csv("graph_metrics.csv",
              ["id", "name", "nodeLabel", "property", "algorithm", "description"],
              GRAPH_METRICS)
    write_csv("measures.csv",
              ["id", "name", "definition", "grain", "aggregation"], MEASURES)

    print("Relationship CSVs:")
    write_csv("has_invoice.csv", ["customer_id", "invoice_id"],
              [{"customer_id": i["customer_id"], "invoice_id": i["id"]} for i in invoices])
    write_csv("belongs_to.csv", ["customer_id", "business_unit_id"], belongs_to)
    write_csv("recognizes.csv", ["business_unit_id", "revenue_entry_id"],
              [{"business_unit_id": r["business_unit_id"], "revenue_entry_id": r["id"]}
               for r in revenue_entries])
    write_csv("supplies.csv", ["supplier_id", "business_unit_id"], supplies)
    # Bridge table for the lakehouse: the supplier-to-business-unit link is
    # many-to-many, so it lives as its own table (supplier_business_units in UC).
    write_csv("supplier_business_units.csv", ["supplierId", "businessUnitId"],
              [{"supplierId": s["supplier_id"], "businessUnitId": s["business_unit_id"]}
               for s in supplies])
    write_csv("has_finding.csv", ["customer_id", "finding_id"],
              [{"customer_id": f["customer_id"], "finding_id": f["id"]} for f in findings])
    write_csv("classified_as.csv",
              ["entity_id", "entity_label", "term_id", "reason", "evaluatedAt", "ruleVersion"],
              classified_as)
    write_csv("defined_by.csv", ["term_id", "rule_id"], DEFINED_BY)
    write_csv("evaluates.csv", ["rule_id", "entity_id"], EVALUATES)
    write_csv("constrains.csv", ["policy_id", "entity_id"], CONSTRAINS)
    write_csv("governs.csv", ["policy_id", "rule_id"], GOVERNS)
    write_csv("applies_to.csv", ["threshold_id", "term_id"], APPLIES_TO)
    write_csv("rule_thresholds.csv", ["rule_id", "threshold_id"], RULE_THRESHOLDS)
    write_csv("scored_by.csv", ["term_id", "metric_id"], SCORED_BY)
    write_csv("measured_by.csv", ["term_id", "measure_id"], MEASURED_BY)
    write_csv("measure_defined_by.csv", ["measure_id", "rule_id"], MEASURE_DEFINED_BY)
    write_csv("maps_to.csv", ["entity_id", "data_source_id"], MAPS_TO)
    write_csv("realized_as.csv", ["entity_id", "instance_id", "instance_label"], realized_as)

    tier1_scores = {t: next(s["riskScore"] for s in suppliers if s["id"] == t) for t in TIER1_IDS}
    cascade_score = next(s["riskScore"] for s in suppliers if s["id"] == CASCADE_ID)
    ground_truth = {
        "schema_version": 2,
        "seed": SEED,
        "as_of_date": AS_OF.isoformat(),
        # Which build this is, so a transcript can be traced back to the data it
        # was captured against. `quarter` is the one the pre-flight compares
        # against on the day: AS_OF is date.today() at generation, so if a
        # calendar quarter rolls between building and demoing, "the most recent
        # full quarter" resolves to a quarter nothing here ever asserted.
        "build_identity": {
            "seed": SEED,
            "as_of_date": AS_OF.isoformat(),
            "git_sha": git_sha(),
            "quarter": DEFAULTED_PERIOD,
        },
        "summary": {
            "customers": len(customers),
            "suppliers": len(suppliers),
            "business_units": len(BUSINESS_UNITS),
            "invoices": len(invoices),
            "revenue_entries": len(revenue_entries),
            "compliance_findings": len(findings),
            "supply_relationships": len(supply_rels),
            "owned_by_edges": owned_by_edges,
        },
        "story1_hidden_glassworks": {
            "cascade_id": CASCADE_ID,
            "cascade_risk_score": cascade_score,
            "tier1_ids": TIER1_IDS,
            "tier1_risk_scores": tier1_scores,
            "business_unit": "BU-03",
            "last_quarter": DEFAULTED_PERIOD,
            "bu03_last_quarter_revenue": bu03_last_quarter,
        },
        "story2_clean_payer": {
            "kestrel_id": KESTREL_ID,
            "jade_id": JADE_ID,
            # The Kestrel group: Jade, the two holdcos between her and the
            # failures, and the four defaults themselves.
            "group_ids": [KESTREL_ID, HARBOUR_ID, TERN_ID, JADE_ID,
                          *KESTREL_DEFAULT_IDS],
            "kestrel_default_ids": list(KESTREL_DEFAULT_IDS),
            # Every defaulted customer in the book. gds.py seeds the weighted
            # propagation on all of them, not just Kestrel's, so the score
            # reflects the whole book's damage rather than one group's.
            "seed_ids": sorted(defaulted_customers),
            "defaulted_period": DEFAULTED_PERIOD,
            "jade_open_invoice_balance": jade_open_balance,
            "jade_credit_limit": jade["creditLimit"],
            "jade_exposure": jade_exposure,
        },
        "classification_cohorts": {
            "high_risk_suppliers": sorted(high_risk_suppliers),
            "delinquent_customers": sorted(delinquent),
            "strategic_accounts": sorted(strategic_accounts),
            "defaulted_customers": sorted(defaulted_customers),
        },
    }
    gt_path = DATA_DIR / "ground_truth.json"
    gt_path.write_text(json.dumps(ground_truth, indent=2) + "\n")
    print(f"  ground_truth.json: {ground_truth['summary']}")
    print(f"  Story 1: BU-03 last-quarter revenue EUR {bu03_last_quarter:,.2f}")
    print(f"  Story 2: Jade credit exposure EUR {jade_exposure:,.2f} "
          f"(committed facility {jade['creditLimit']:,.2f}, of which "
          f"{jade_open_balance:,.2f} drawn)")


if __name__ == "__main__":
    main()
