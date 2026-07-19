"""Synthetic data generator for the supplier-risk-graph demo.

Writes one CSV per node/table type and one per relationship type to data/, plus
ground_truth.json describing the two demo stories and the new dataset counts.

The demo is built from scratch around two graph-native stories:

- Story 1 (the hidden glassworks): five clean tier-1 bottle suppliers all feed
  the Americas business unit (BU-03) and are all fed by one middling-risk
  tier-2 supplier, Cascade Glassworks (SUP-901). No flat column surfaces
  Cascade; only betweenness over the supply network does.
- Story 2 (the clean payer in a bad family): Jade (CUST-904) is a spotless
  platinum account whose parent holding company (Kestrel, CUST-901) also owns
  two defaulted siblings (Marlin, Pelican). No column ties Jade to the risk;
  only ownership propagation over the graph does.

The generator plants only the four column-findable classifications (Strategic
Account, Defaulted Customer, Delinquent Customer, High-Risk Supplier). The two
graph-native terms (Critical Supplier, Ownership Risk) are resolved live at
demo time and are never pre-planted.

Deterministic: fixed seed, frozen as-of date, all daysLate values computed once
at generation time and stored.

Run with: uv run generate_data.py
"""

from __future__ import annotations

import csv
import json
import random
from datetime import date, timedelta
from pathlib import Path

SEED = 42
AS_OF = date(2026, 7, 1)
EVALUATED_AT = "2026-07-01T00:00:00Z"
RULE_VERSION = "v1.0"
CURRENCY = "EUR"

# Background population sizes (protagonists are added on top of these).
N_CUSTOMERS = 500
N_SUPPLIERS = 150
N_PLATINUM = 60
N_GOLD = 140
N_STRATEGIC_BG = 6  # background platinum accounts also flagged Strategic, for realism
N_DELINQUENT = 15  # background customers planted to satisfy the Delinquent rule
N_FILLER_PARENTS = 12  # filler ownership families (2-4 children each)
N_FILLER_SUP_SOURCES = 20  # filler supplier-to-supplier sources (1-3 targets each)

SUPPLIER_RISK_THRESHOLD = 70  # riskScore on a 0-100 scale
LATE_DAYS_THRESHOLD = 60  # days

DATA_DIR = Path(__file__).parent / "data"

# --- Protagonist ids (reserved high block, hand-named, excluded from draws) ---
CASCADE_ID = "SUP-901"
TIER1_IDS = ["SUP-902", "SUP-903", "SUP-904", "SUP-905", "SUP-906"]
PROTAGONIST_SUPPLIER_IDS = {CASCADE_ID, *TIER1_IDS}

KESTREL_ID = "CUST-901"
MARLIN_ID = "CUST-902"
PELICAN_ID = "CUST-903"
JADE_ID = "CUST-904"
PROTAGONIST_CUSTOMER_IDS = {KESTREL_ID, MARLIN_ID, PELICAN_ID, JADE_ID}

DEFAULTED_PERIOD = "2026-Q2"
Q2_2026_PERIODS = {"2026-04", "2026-05", "2026-06"}

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
# Filler supplier name suffixes matched to the supplier's category, so a
# supplier's name reads consistently with its specialty (no "Ingredients" named
# packaging supplier). "Glassworks" is reserved for Cascade, so no filler shares
# it. Protagonist stems are excluded from NAME_STEMS, so no filler collides.
SUPPLIER_SUFFIXES_BY_CATEGORY = {
    "ingredients": ["Malt Supply", "Hops Co", "Ingredients", "Flavor Co"],
    "packaging": ["Packaging", "Bottling Supply", "Labels", "Containers"],
    "logistics": ["Logistics", "Transport", "Freight"],
    "equipment": ["Equipment", "Cooling Systems", "Brewing Systems"],
    "services": ["Services", "Consulting", "Maintenance"],
}

SUPPLIER_CATEGORIES = ["ingredients", "packaging", "logistics", "equipment", "services"]
# Subcategory vocabulary by category. "raw glass" is reserved for Cascade.
SUBCATEGORIES = {
    "ingredients": ["malt", "hops", "sugar", "flavorings"],
    "packaging": ["glass bottles", "cans", "caps", "labels"],
    "logistics": ["freight", "warehousing"],
    "equipment": ["brewing equipment", "cooling systems"],
    "services": ["consulting", "maintenance"],
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
]

BUSINESS_TERMS = [
    {"id": "TERM-01", "name": "Strategic Account", "definition": "A platinum customer flagged strategic by account management."},
    {"id": "TERM-02", "name": "Defaulted Customer", "definition": "A customer with a recorded default in the snapshot."},
    {"id": "TERM-03", "name": "Delinquent Customer", "definition": "A customer more than 60 days late on each of its last three invoices."},
    {"id": "TERM-04", "name": "High-Risk Supplier", "definition": "A supplier whose procurement risk score meets or exceeds the threshold."},
    {"id": "TERM-05", "name": "Critical Supplier", "definition": "A supplier the network disproportionately depends on: the narrowest bridge on a business unit's multi-tier supply paths."},
    {"id": "TERM-06", "name": "Ownership Risk", "definition": "A customer inside an ownership group that contains a defaulted member, so its risk exceeds its own record."},
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
     "expression": "highest-betweenness bridge on a business unit's multi-tier supply paths, at or above the supply concentration threshold",
     "description": "The supplier the network most depends on across multi-tier supply paths into a business unit; read from precomputed betweenness.",
     "threshold": ""},
    {"id": "RULE-06", "name": "Ownership Risk Rule",
     "expression": "member of an OWNED_BY group (transitive) containing a Defaulted Customer, with propagated risk >= ownership contagion threshold",
     "description": "A customer whose ownership group contains a defaulted member, with propagated risk above the contagion threshold; read from precomputed PageRank.",
     "threshold": ""},
]

POLICIES = [
    {"id": "POL-01", "name": "Credit Risk Policy", "type": "Credit"},
    {"id": "POL-02", "name": "Supply Chain Resilience Policy", "type": "Procurement"},
    {"id": "POL-03", "name": "Compliance (KYC) Policy", "type": "Compliance"},
]

THRESHOLDS = [
    {"id": "THR-01", "name": "Supplier Risk Threshold", "value": SUPPLIER_RISK_THRESHOLD, "currency": ""},
    {"id": "THR-02", "name": "Late Payment Threshold", "value": LATE_DAYS_THRESHOLD, "currency": ""},
    # The two graph-native thresholds are left empty here on purpose: Phase 2
    # (gds.py) fills them from the computed betweenness / PageRank distribution.
    {"id": "THR-03", "name": "Supply Concentration Threshold", "value": "", "currency": ""},
    {"id": "THR-04", "name": "Ownership Contagion Threshold", "value": "", "currency": ""},
]

# term -> defining rule, by position.
DEFINED_BY = [
    {"term_id": t["id"], "rule_id": r["id"]}
    for t, r in zip(BUSINESS_TERMS, BUSINESS_RULES)
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
    for e, d in zip(ENTITIES, DATA_SOURCES)
]


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
            "parentCustomerId": "",
            "defaultedPeriod": "",
        })

    platinum = [c["id"] for c in customers if c["segment"] == "platinum"]
    strategic_bg = rng.sample(platinum, N_STRATEGIC_BG)
    delinquent_pool = [c["id"] for c in customers if c["segment"] in ("gold", "silver")]
    delinquent_bg = rng.sample(delinquent_pool, N_DELINQUENT)

    cohorts = {"strategic_bg": strategic_bg, "delinquent_bg": delinquent_bg}
    return customers, cohorts


def make_protagonist_customers(rng: random.Random) -> list[dict]:
    """The four Story 2 protagonists. creditLimit for Jade is finalized later."""
    return [
        {"id": KESTREL_ID, "name": "Kestrel Holdings", "segment": "gold",
         "profitabilityTrend": "stable", "churnRisk": "low", "upsellScore": 40,
         "creditLimit": credit_limit_for(rng, "gold"),
         "parentCustomerId": "", "defaultedPeriod": ""},
        {"id": MARLIN_ID, "name": "Marlin Wholesale Drinks", "segment": "gold",
         "profitabilityTrend": "declining", "churnRisk": "high", "upsellScore": 22,
         "creditLimit": credit_limit_for(rng, "gold"),
         "parentCustomerId": KESTREL_ID, "defaultedPeriod": DEFAULTED_PERIOD},
        {"id": PELICAN_ID, "name": "Pelican Beverage Retail", "segment": "gold",
         "profitabilityTrend": "declining", "churnRisk": "high", "upsellScore": 18,
         "creditLimit": credit_limit_for(rng, "gold"),
         "parentCustomerId": KESTREL_ID, "defaultedPeriod": DEFAULTED_PERIOD},
        {"id": JADE_ID, "name": "Jade Beverage Distribution", "segment": "platinum",
         "profitabilityTrend": "stable", "churnRisk": "low", "upsellScore": 88,
         "creditLimit": 0,  # finalized in main so exposure lands near 800K
         "parentCustomerId": KESTREL_ID, "defaultedPeriod": ""},
    ]


def make_suppliers(rng: random.Random) -> list[dict]:
    """Build the 150 background suppliers plus the six Story 1 protagonists."""
    # One shuffled, per-category name pool so each supplier's name suffix matches
    # its category. Pools are disjoint by suffix, so no full name repeats.
    name_pools = {
        cat: [f"{stem} {suffix}" for stem in NAME_STEMS for suffix in suffixes]
        for cat, suffixes in SUPPLIER_SUFFIXES_BY_CATEGORY.items()
    }
    for pool in name_pools.values():
        rng.shuffle(pool)

    suppliers = []
    for i in range(N_SUPPLIERS):
        category = rng.choice(SUPPLIER_CATEGORIES)
        suppliers.append({
            "id": f"SUP-{i + 1:03d}",
            "name": name_pools[category].pop(),
            "category": category,
            "subcategory": rng.choice(SUBCATEGORIES[category]),
            # Uniform spread across 0-100 leaves a believable minority at or
            # above the risk threshold.
            "riskScore": rng.randint(5, 95),
        })

    # Cascade: middling risk (60-69), the hidden tier-2 raw-glass supplier.
    suppliers.append({"id": CASCADE_ID, "name": "Cascade Glassworks",
                      "category": "packaging", "subcategory": "raw glass",
                      "riskScore": rng.randint(60, 69)})
    # The five clean tier-1 bottle suppliers (below 40 so no score filter finds them).
    tier1_names = ["Harbor Bottling Supply", "Summit Glass Packaging",
                   "Ironbridge Containers", "Clearwater Bottles", "Aurora Packaging Co"]
    for sup_id, name in zip(TIER1_IDS, tier1_names):
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
    """Supplier-to-supplier SUPPLIES edges.

    Cascade (SUP-901) feeds all five tier-1 bottle suppliers. Filler tier-2
    suppliers feed scattered background suppliers, but each filler source picks
    targets of DISTINCT subcategories so it can never reproduce Cascade's
    convergence (several same-subcategory suppliers all serving one BU).
    """
    rels = [{"fromSupplierId": CASCADE_ID, "toSupplierId": t} for t in TIER1_IDS]

    background = [s for s in suppliers if s["id"] not in PROTAGONIST_SUPPLIER_IDS]
    sources = rng.sample(background, N_FILLER_SUP_SOURCES)
    for source in sources:
        candidates = [s for s in background if s["id"] != source["id"]]
        rng.shuffle(candidates)
        used_subcats: set[str] = set()
        picked = 0
        want = rng.randint(1, 3)
        for cand in candidates:
            if cand["subcategory"] in used_subcats:
                continue
            used_subcats.add(cand["subcategory"])
            rels.append({"fromSupplierId": source["id"], "toSupplierId": cand["id"]})
            picked += 1
            if picked == want:
                break
    return rels


def assign_filler_ownership(rng: random.Random, customers: list[dict]) -> None:
    """Designate filler ownership families among the background customers.

    Each filler parent owns 2-4 children. No filler child is a protagonist, so
    no filler family can contain a defaulted member (only Marlin and Pelican
    carry a default, and both belong to the Kestrel family).
    """
    by_id = {c["id"]: c for c in customers}
    bg_ids = [c["id"] for c in customers if c["id"] not in PROTAGONIST_CUSTOMER_IDS]
    parents = rng.sample(bg_ids, N_FILLER_PARENTS)
    parent_set = set(parents)
    available = [cid for cid in bg_ids if cid not in parent_set]
    rng.shuffle(available)
    for parent in parents:
        for _ in range(rng.randint(2, 4)):
            if not available:
                break
            child = available.pop()
            by_id[child]["parentCustomerId"] = parent


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
        if cid == KESTREL_ID:
            continue  # the parent holding company has no invoices
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

    The Americas (BU-03) entries for the last quarter (2026-Q2) are sized so
    their sum lands near the 4.2M Story 1 exposure figure.
    """
    periods = []
    year, month = 2025, 7
    for _ in range(12):
        periods.append(f"{year}-{month:02d}")
        month += 1
        if month > 12:
            year, month = year + 1, 1

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
            if bu["id"] == "BU-03" and period in Q2_2026_PERIODS:
                add(bu["id"], period, rng.uniform(1_350_000, 1_450_000), True)
            else:
                add(bu["id"], period, rng.uniform(200_000, 900_000), rng.random() > 0.05)
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

    # Cascade must be the unique convergence point: the only supplier whose
    # supplier-to-supplier targets include >=2 same-subcategory suppliers that
    # all serve one common business unit. (Betweenness itself is a Phase 2
    # computation; here we assert only the structural invariant.)
    targets_by_source: dict[str, list[str]] = {}
    for rel in supply_rels:
        targets_by_source.setdefault(rel["fromSupplierId"], []).append(rel["toSupplierId"])
    convergence_sources = set()
    for source, targets in targets_by_source.items():
        by_subcat: dict[str, list[str]] = {}
        for t in targets:
            by_subcat.setdefault(by_id[t]["subcategory"], []).append(t)
        for group in by_subcat.values():
            if len(group) < 2:
                continue
            common = set.intersection(*(bus_by_supplier.get(t, set()) for t in group))
            if common:
                convergence_sources.add(source)
    assert convergence_sources == {CASCADE_ID}, (
        f"Cascade must be the unique convergence point, got {convergence_sources}")


def check_story2(customers: list[dict], invoices: list[dict],
                 findings: list[dict], delinquent: set[str],
                 strategic_ids: set[str]) -> None:
    by_id = {c["id"]: c for c in customers}
    jade = by_id[JADE_ID]
    assert jade["segment"] == "platinum", "Jade must be platinum"
    assert JADE_ID in strategic_ids, "Jade must be classified Strategic Account"
    assert jade["defaultedPeriod"] == "", "Jade must not carry a defaultedPeriod"
    assert JADE_ID not in delinquent, "Jade must not be delinquent"
    assert jade["parentCustomerId"] == KESTREL_ID, "Jade must be owned by Kestrel"
    jade_invoices = [i for i in invoices if i["customer_id"] == JADE_ID]
    assert jade_invoices and all(i["status"] == "open" for i in jade_invoices), \
        "Jade's invoices must all be open"
    assert not any(i["status"] == "overdue" for i in jade_invoices), \
        "Jade must have no overdue invoice"
    assert JADE_ID not in {f["customer_id"] for f in findings}, "Jade must have no finding"

    for sib in (MARLIN_ID, PELICAN_ID):
        assert by_id[sib]["defaultedPeriod"] == DEFAULTED_PERIOD, f"{sib} must be defaulted"
        assert by_id[sib]["parentCustomerId"] == KESTREL_ID, f"{sib} must be owned by Kestrel"

    kestrel = by_id[KESTREL_ID]
    assert kestrel["parentCustomerId"] == "", "Kestrel must have no parent"
    assert not any(i["customer_id"] == KESTREL_ID for i in invoices), "Kestrel has no invoices"
    assert KESTREL_ID not in {f["customer_id"] for f in findings}, "Kestrel has no findings"

    # No filler ownership family may contain a defaulted member.
    defaulted = {c["id"] for c in customers if c["defaultedPeriod"]}
    assert defaulted == {MARLIN_ID, PELICAN_ID}, "only Marlin and Pelican may be defaulted"
    for cid in defaulted:
        assert by_id[cid]["parentCustomerId"] == KESTREL_ID, "defaulters must be Kestrel's"
    # No customer may be owned by a defaulted parent (defaulters own no one).
    assert not any(c["parentCustomerId"] in defaulted for c in customers), \
        "no family may be headed by a defaulted parent"


def check_exposure(revenue_entries: list[dict], bu03_last_quarter: float,
                   jade_exposure: float) -> None:
    assert 3_800_000 <= bu03_last_quarter <= 4_600_000, \
        f"BU-03 last-quarter revenue {bu03_last_quarter} outside the 4.2M band"
    assert 750_000 <= jade_exposure <= 850_000, \
        f"Jade exposure {jade_exposure} outside the 800K band"


def check_referential(customers: list[dict], suppliers: list[dict],
                      supply_rels: list[dict]) -> None:
    customer_ids = {c["id"] for c in customers}
    supplier_ids = {s["id"] for s in suppliers}
    for c in customers:
        assert c["creditLimit"], f"{c['id']} must have a creditLimit"
        if c["parentCustomerId"]:
            assert c["parentCustomerId"] in customer_ids, \
                f"{c['id']} parent {c['parentCustomerId']} missing"
    for s in suppliers:
        assert s["subcategory"], f"{s['id']} must have a subcategory"
    for rel in supply_rels:
        assert rel["fromSupplierId"] in supplier_ids, f"unknown {rel['fromSupplierId']}"
        assert rel["toSupplierId"] in supplier_ids, f"unknown {rel['toSupplierId']}"


def write_csv(name: str, fieldnames: list[str], rows: list[dict]) -> None:
    path = DATA_DIR / name
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    print(f"  {name}: {len(rows)} rows")


def main() -> None:
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

    assign_filler_ownership(rng, customers)

    delinquent_set = set(cohorts["delinquent_bg"])
    invoices = make_invoices(rng, customers, delinquent_set)

    # Finalize Jade's credit line so exposure (open balance + credit line) lands
    # near 800K. Round to a round thousand like every other customer's limit so
    # Jade's line does not stand out as the one fractional value; the exact
    # exposure is read off the data and quoted as approximate.
    jade_open_balance = round(
        sum(i["amount"] for i in invoices if i["customer_id"] == JADE_ID), 2)
    jade = next(c for c in customers if c["id"] == JADE_ID)
    jade["creditLimit"] = round((800_000 - jade_open_balance) / 1000) * 1000

    revenue_entries = make_revenue_entries(rng)
    findings = make_findings(rng, customers)
    add_payment_features(customers, invoices)

    supplies = make_supplies(rng, suppliers)
    supply_rels = make_supply_relationships(rng, suppliers)

    # OWNED_BY edges: one row per customer that carries a parent.
    owned_by = [
        {"customer_id": c["id"], "parent_customer_id": c["parentCustomerId"]}
        for c in customers if c["parentCustomerId"]
    ]

    # Recompute the delinquent cohort from the data (must equal the plant).
    delinquent = compute_delinquent(customers, invoices)
    assert set(delinquent) == delinquent_set, "delinquent cohort drifted from the plant"
    high_risk_suppliers = [
        s["id"] for s in suppliers
        if s["id"] not in PROTAGONIST_SUPPLIER_IDS and s["riskScore"] >= SUPPLIER_RISK_THRESHOLD
    ]
    strategic_accounts = [JADE_ID] + cohorts["strategic_bg"]
    defaulted_customers = [MARLIN_ID, PELICAN_ID]

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
            if r["business_unit_id"] == "BU-03" and r["period"] in Q2_2026_PERIODS), 2)
    jade_exposure = round(jade_open_balance + jade["creditLimit"], 2)

    # Self-checks (offline, fail loud).
    strategic_ids = {row["entity_id"] for row in classified_as if row["term_id"] == "TERM-01"}
    check_story1(suppliers, supplies, supply_rels)
    check_story2(customers, invoices, findings, delinquent_set, strategic_ids)
    check_exposure(revenue_entries, bu03_last_quarter, jade_exposure)
    check_referential(customers, suppliers, supply_rels)

    print("Instance node / table CSVs:")
    write_csv("customers.csv",
              ["id", "businessUnitId", "name", "segment", "profitabilityTrend", "churnRisk",
               "upsellScore", "avgDaysLate", "overdueShare", "parentCustomerId",
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

    print("Knowledge-layer CSVs:")
    write_csv("entities.csv", ["id", "name", "description"], ENTITIES)
    write_csv("business_terms.csv", ["id", "name", "definition"], BUSINESS_TERMS)
    write_csv("business_rules.csv",
              ["id", "name", "expression", "description", "threshold"], BUSINESS_RULES)
    write_csv("policies.csv", ["id", "name", "type"], POLICIES)
    write_csv("thresholds.csv", ["id", "name", "value", "currency"], THRESHOLDS)
    write_csv("data_sources.csv", ["id", "name", "system", "table"], DATA_SOURCES)

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
    write_csv("owned_by.csv", ["customer_id", "parent_customer_id"], owned_by)
    write_csv("classified_as.csv",
              ["entity_id", "entity_label", "term_id", "reason", "evaluatedAt", "ruleVersion"],
              classified_as)
    write_csv("defined_by.csv", ["term_id", "rule_id"], DEFINED_BY)
    write_csv("evaluates.csv", ["rule_id", "entity_id"], EVALUATES)
    write_csv("constrains.csv", ["policy_id", "entity_id"], CONSTRAINS)
    write_csv("governs.csv", ["policy_id", "rule_id"], GOVERNS)
    write_csv("applies_to.csv", ["threshold_id", "term_id"], APPLIES_TO)
    write_csv("maps_to.csv", ["entity_id", "data_source_id"], MAPS_TO)
    write_csv("realized_as.csv", ["entity_id", "instance_id", "instance_label"], realized_as)

    tier1_scores = {t: next(s["riskScore"] for s in suppliers if s["id"] == t) for t in TIER1_IDS}
    cascade_score = next(s["riskScore"] for s in suppliers if s["id"] == CASCADE_ID)
    ground_truth = {
        "schema_version": 2,
        "seed": SEED,
        "as_of_date": AS_OF.isoformat(),
        "summary": {
            "customers": len(customers),
            "suppliers": len(suppliers),
            "business_units": len(BUSINESS_UNITS),
            "invoices": len(invoices),
            "revenue_entries": len(revenue_entries),
            "compliance_findings": len(findings),
            "supply_relationships": len(supply_rels),
            "owned_by_edges": len(owned_by),
        },
        "story1_hidden_glassworks": {
            "cascade_id": CASCADE_ID,
            "cascade_risk_score": cascade_score,
            "tier1_ids": TIER1_IDS,
            "tier1_risk_scores": tier1_scores,
            "business_unit": "BU-03",
            "last_quarter": "2026-Q2",
            "bu03_last_quarter_revenue": bu03_last_quarter,
        },
        "story2_clean_payer": {
            "kestrel_id": KESTREL_ID,
            "jade_id": JADE_ID,
            "sibling_ids": [MARLIN_ID, PELICAN_ID],
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
    print(f"  Story 2: Jade exposure EUR {jade_exposure:,.2f} "
          f"(open {jade_open_balance:,.2f} + credit {jade['creditLimit']:,.2f})")


if __name__ == "__main__":
    main()
