"""Synthetic data generator for the supplier-risk-graph demo.

Writes one CSV per node type and one per relationship type to data/, plus
ground_truth.json holding the expected answer set for each of the 6
validation questions and the Q4 exposure plant: a business unit exposed through
mid-risk suppliers. The data also seeds a cohort of customers near the risky
group without tripping the rule; the Q5/Q6 GDS kNN pass surfaces those at
analytics time, so the candidates emerge from the run and are not recorded here.
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

N_CUSTOMERS = 100
N_SUPPLIERS = 30
N_HIGH_RISK_SUPPLIERS = 5  # Q4: riskScore >= SUPPLIER_RISK_THRESHOLD
N_PLATINUM = 15
N_GOLD = 25
N_STRATEGIC = 8  # subset of platinum, pre-planted CLASSIFIED_AS
N_AT_RISK = 3  # subset of strategic hitting all four Q6 conditions
N_KYC_VIOLATORS = 6  # Q2: includes the first at-risk strategic account
N_RISKY = 5  # Q5: includes the first at-risk strategic account
N_MID_RISK_SUPPLIERS = 4  # GDS Q4: exposure band, every score below the rule threshold
N_SIMILAR = 4  # GDS Q5/Q6: customers near the risky cohort without tripping the rule

MATERIALITY_THRESHOLD = 100_000  # EUR, Q1
SUPPLIER_RISK_THRESHOLD = 70  # riskScore on a 0-100 scale, Q4
LATE_DAYS_THRESHOLD = 60  # days, Q5
MID_RISK_LOW, MID_RISK_HIGH = 60, 69  # GDS Q4 exposure band, exclusive to the plant
EXPOSURE_BU = "BU-03"  # GDS Q4: supplied only by the mid-risk band

DATA_DIR = Path(__file__).parent / "data"

NAME_STEMS = [
    "Alder", "Birch", "Cedar", "Delta", "Ember", "Fjord", "Granite", "Harbor",
    "Iris", "Juniper", "Kestrel", "Lumen", "Meridian", "Northwind", "Orchid",
    "Pinnacle", "Quartz", "Ridgeline", "Summit", "Tidal", "Umber", "Vector",
    "Willow", "Zephyr", "Atlas",
]
CUSTOMER_SUFFIXES = [
    "Beverages", "Retail", "Distribution", "Trading", "Hospitality",
    "Markets", "Foods", "Drinks Co", "Group", "Wholesale",
]
SUPPLIER_SUFFIXES = [
    "Malt Supply", "Packaging", "Logistics", "Glassworks", "Ingredients",
    "Equipment", "Labels", "Transport", "Hops Co", "Cooling Systems",
]
SUPPLIER_CATEGORIES = ["ingredients", "packaging", "logistics", "equipment", "services"]

BUSINESS_UNITS = [
    {"id": "BU-01", "name": "Northern Europe", "region": "EMEA"},
    {"id": "BU-02", "name": "Southern Europe", "region": "EMEA"},
    {"id": "BU-03", "name": "Americas", "region": "AMER"},
    {"id": "BU-04", "name": "Asia Pacific", "region": "APAC"},
    {"id": "BU-05", "name": "Africa & Middle East", "region": "EMEA"},
]
UNRECONCILED_BUS = ["BU-02", "BU-04"]  # Q1: planted above the materiality threshold

EDM_ENTITIES = [
    {"id": "EDM-01", "name": "Customer", "description": "A party that buys goods or services from the company."},
    {"id": "EDM-02", "name": "Supplier", "description": "A party that provides goods or services to the company."},
    {"id": "EDM-03", "name": "BusinessUnit", "description": "An organizational unit that recognizes revenue and owns customer relationships."},
    {"id": "EDM-04", "name": "Invoice", "description": "A billing document issued to a customer with a due date and settlement status."},
    {"id": "EDM-05", "name": "Payment", "description": "A settlement received against an invoice."},
    {"id": "EDM-06", "name": "RevenueEntry", "description": "A recognized revenue amount for a business unit in a period, reconciled or not."},
    {"id": "EDM-07", "name": "ComplianceFinding", "description": "An open or closed compliance issue raised against a customer."},
]

BUSINESS_TERMS = [
    {"id": "TERM-01", "name": "Platinum Customer", "definition": "A customer in the platinum segment, the top commercial tier."},
    {"id": "TERM-02", "name": "Strategic Account", "definition": "A platinum customer flagged strategic by account management."},
    {"id": "TERM-03", "name": "High-Risk Supplier", "definition": "A supplier whose procurement risk score meets or exceeds the supplier risk threshold."},
    {"id": "TERM-04", "name": "Risky Customer", "definition": "A customer more than 60 days late on payments for each of their last 3 invoices."},
    {"id": "TERM-05", "name": "Unreconciled Revenue", "definition": "Recognized revenue not yet reconciled; material when it exceeds the materiality threshold per business unit."},
]

BUSINESS_RULES = [
    {"id": "RULE-01", "name": "Platinum Customer Rule", "expression": "customer.segment = 'platinum'", "description": "Membership of the platinum commercial segment.", "threshold": ""},
    {"id": "RULE-02", "name": "Strategic Account Rule", "expression": "customer.segment = 'platinum' AND flagged strategic by account management", "description": "Platinum customers designated strategic.", "threshold": ""},
    {"id": "RULE-03", "name": "High-Risk Supplier Rule", "expression": "supplier.riskScore >= 70", "description": "Procurement risk score at or above the supplier risk threshold.", "threshold": SUPPLIER_RISK_THRESHOLD},
    {"id": "RULE-04", "name": "Risky Customer Rule", "expression": "all(last 3 invoices WHERE invoice.daysLate > 60)", "description": "More than 60 days late on each of the last three invoices.", "threshold": LATE_DAYS_THRESHOLD},
    {"id": "RULE-05", "name": "Unreconciled Revenue Rule", "expression": "sum(revenueEntry.amount WHERE reconciled = false) > materiality threshold", "description": "Unreconciled revenue per business unit above the materiality threshold.", "threshold": MATERIALITY_THRESHOLD},
]

POLICIES = [
    {"id": "POL-01", "name": "KYC Policy", "type": "Compliance"},
    {"id": "POL-02", "name": "Procurement Policy", "type": "Procurement"},
    {"id": "POL-03", "name": "Revenue Recognition Policy", "type": "Finance"},
]

THRESHOLDS = [
    {"id": "THR-01", "name": "Materiality Threshold", "value": MATERIALITY_THRESHOLD, "currency": CURRENCY},
    {"id": "THR-02", "name": "Supplier Risk Threshold", "value": SUPPLIER_RISK_THRESHOLD, "currency": ""},
    {"id": "THR-03", "name": "Late Payment Threshold", "value": LATE_DAYS_THRESHOLD, "currency": ""},
]

DATA_SOURCES = [
    {"id": "DS-01", "name": "customers", "system": "Databricks Unity Catalog", "table": "supplier_risk.customers"},
    {"id": "DS-02", "name": "suppliers", "system": "Databricks Unity Catalog", "table": "supplier_risk.suppliers"},
    {"id": "DS-03", "name": "business_units", "system": "Databricks Unity Catalog", "table": "supplier_risk.business_units"},
    {"id": "DS-04", "name": "invoices", "system": "Databricks Unity Catalog", "table": "supplier_risk.invoices"},
    {"id": "DS-05", "name": "payments", "system": "Databricks Unity Catalog", "table": "supplier_risk.payments"},
    {"id": "DS-06", "name": "revenue_entries", "system": "Databricks Unity Catalog", "table": "supplier_risk.revenue_entries"},
    {"id": "DS-07", "name": "compliance_findings", "system": "Databricks Unity Catalog", "table": "supplier_risk.compliance_findings"},
]

DEFINED_BY = [{"term_id": f"TERM-0{i}", "rule_id": f"RULE-0{i}"} for i in range(1, 6)]

EVALUATES = [
    {"rule_id": "RULE-01", "edm_entity_id": "EDM-01"},
    {"rule_id": "RULE-02", "edm_entity_id": "EDM-01"},
    {"rule_id": "RULE-03", "edm_entity_id": "EDM-02"},
    {"rule_id": "RULE-04", "edm_entity_id": "EDM-01"},
    {"rule_id": "RULE-04", "edm_entity_id": "EDM-04"},
    {"rule_id": "RULE-05", "edm_entity_id": "EDM-06"},
    {"rule_id": "RULE-05", "edm_entity_id": "EDM-03"},
]

CONSTRAINS = [
    {"policy_id": "POL-01", "edm_entity_id": "EDM-01"},
    {"policy_id": "POL-02", "edm_entity_id": "EDM-02"},
    {"policy_id": "POL-03", "edm_entity_id": "EDM-06"},
]

APPLIES_TO = [
    {"threshold_id": "THR-01", "term_id": "TERM-05"},
    {"threshold_id": "THR-02", "term_id": "TERM-03"},
    {"threshold_id": "THR-03", "term_id": "TERM-04"},
]

MAPS_TO = [{"edm_entity_id": f"EDM-0{i}", "data_source_id": f"DS-0{i}"} for i in range(1, 8)]


def make_names(rng: random.Random, suffixes: list[str], count: int) -> list[str]:
    combos = [f"{stem} {suffix}" for stem in NAME_STEMS for suffix in suffixes]
    return rng.sample(combos, count)


def make_customers(rng: random.Random) -> tuple[list[dict], dict[str, list[str]]]:
    """Build customer rows plus the planted cohorts keyed by role."""
    names = make_names(rng, CUSTOMER_SUFFIXES, N_CUSTOMERS)
    segments = (
        ["platinum"] * N_PLATINUM
        + ["gold"] * N_GOLD
        + ["silver"] * (N_CUSTOMERS - N_PLATINUM - N_GOLD)
    )
    rng.shuffle(segments)

    customers = []
    for i in range(N_CUSTOMERS):
        customers.append({
            "id": f"CUST-{i + 1:03d}",
            "name": names[i],
            "segment": segments[i],
            "profitabilityTrend": rng.choice(["improving", "stable", "declining"]),
            "churnRisk": rng.choice(["low", "medium", "high"]),
        })

    by_id = {c["id"]: c for c in customers}
    platinum = [c["id"] for c in customers if c["segment"] == "platinum"]
    strategic = rng.sample(platinum, N_STRATEGIC)
    at_risk = strategic[:N_AT_RISK]
    non_strategic = [c["id"] for c in customers if c["id"] not in strategic]
    risky = [at_risk[0]] + rng.sample(non_strategic, N_RISKY - 1)
    kyc_pool = [cid for cid in non_strategic if cid not in risky]
    kyc = [at_risk[0]] + rng.sample(kyc_pool, N_KYC_VIOLATORS - 1)

    # Deal the upsell scores: the three highest go to platinum customers so Q3
    # has clear stars, the rest are shuffled across everyone else.
    stars = set(rng.sample(platinum, 3))
    scores = sorted(rng.sample(range(101), N_CUSTOMERS), reverse=True)
    top, rest = scores[:3], scores[3:]
    rng.shuffle(rest)
    for customer in customers:
        customer["upsellScore"] = top.pop() if customer["id"] in stars else rest.pop()

    # Q6: at-risk strategic accounts hit every condition; the rest must miss one,
    # so pin their trend away from 'declining'.
    for cid in strategic:
        if cid in at_risk:
            by_id[cid]["profitabilityTrend"] = "declining"
            by_id[cid]["churnRisk"] = "high"
        else:
            by_id[cid]["profitabilityTrend"] = rng.choice(["improving", "stable"])

    # GDS Q5/Q6 plant: the risky cohort clusters on high churn and declining
    # profitability, and the similar cohort shares that profile without
    # tripping the last-3-invoices rule (its invoice pattern is planted in
    # make_invoices). Kept out of the strategic and KYC cohorts so the
    # similarity story stays clean.
    similar_pool = [cid for cid in non_strategic if cid not in risky and cid not in kyc]
    similar = rng.sample(similar_pool, N_SIMILAR)
    for cid in risky + similar:
        by_id[cid]["profitabilityTrend"] = "declining"
        by_id[cid]["churnRisk"] = "high"

    cohorts = {
        "platinum": platinum,
        "strategic": strategic,
        "at_risk": at_risk,
        "risky": risky,
        "kyc": kyc,
        "similar": similar,
    }
    return customers, cohorts


def is_mid_risk(supplier: dict) -> bool:
    return MID_RISK_LOW <= supplier["riskScore"] <= MID_RISK_HIGH


def make_suppliers(rng: random.Random) -> list[dict]:
    """Build supplier rows in three exclusive score bands.

    High (>= rule threshold, Q4), mid (the GDS exposure plant), and low
    (capped at 54 so a score alone identifies its band).
    """
    names = make_names(rng, SUPPLIER_SUFFIXES, N_SUPPLIERS)
    n_low = N_SUPPLIERS - N_HIGH_RISK_SUPPLIERS - N_MID_RISK_SUPPLIERS
    scores = (
        rng.sample(range(SUPPLIER_RISK_THRESHOLD, 99), N_HIGH_RISK_SUPPLIERS)
        + rng.sample(range(MID_RISK_LOW, MID_RISK_HIGH + 1), N_MID_RISK_SUPPLIERS)
        + rng.sample(range(5, 55), n_low)
    )
    rng.shuffle(scores)
    return [
        {
            "id": f"SUP-{i + 1:03d}",
            "name": names[i],
            "category": rng.choice(SUPPLIER_CATEGORIES),
            "riskScore": scores[i],
        }
        for i in range(N_SUPPLIERS)
    ]


def make_supplies(rng: random.Random, suppliers: list[dict]) -> list[dict]:
    """Each supplier supplies 2 to 4 business units so risk propagation has paths.

    The exposure BU is supplied only by the mid-risk band: no single score
    crosses the rule threshold, but the aggregate tops every other business
    unit. That is the "propagation finds what the flat filter misses" plant.
    """
    other_bus = [bu["id"] for bu in BUSINESS_UNITS if bu["id"] != EXPOSURE_BU]
    supplies = []
    for supplier in suppliers:
        if is_mid_risk(supplier):
            bus = [EXPOSURE_BU] + rng.sample(other_bus, rng.randint(1, 3))
        else:
            bus = rng.sample(other_bus, rng.randint(2, 4))
        supplies.extend({"supplier_id": supplier["id"], "business_unit_id": bu} for bu in bus)
    return supplies


def normal_invoice(rng: random.Random, inv_id: str, customer_id: str) -> dict:
    """An invoice whose daysLate never exceeds the 60-day threshold."""
    issue = AS_OF - timedelta(days=rng.randint(20, 380))
    due = issue + timedelta(days=30)
    amount = round(rng.uniform(800, 45_000), 2)
    row = {
        "id": inv_id,
        "customer_id": customer_id,
        "amount": amount,
        "currency": CURRENCY,
        "issueDate": issue.isoformat(),
        "dueDate": due.isoformat(),
        "paidDate": "",
        "daysLate": 0,
        "status": "open",
    }
    if due >= AS_OF:
        return row
    late = rng.choices(
        [0, rng.randint(1, 30), rng.randint(31, LATE_DAYS_THRESHOLD)], weights=[6, 3, 1]
    )[0]
    paid = due + timedelta(days=late)
    if paid <= AS_OF:
        row.update({"paidDate": paid.isoformat(), "daysLate": late, "status": "paid"})
    else:
        row.update({"daysLate": (AS_OF - due).days, "status": "overdue"})
    return row


def settled_invoice(rng: random.Random, inv_id: str, customer_id: str) -> dict:
    """An older invoice paid at most 20 days late, history filler for planted cohorts."""
    issue = AS_OF - timedelta(days=rng.randint(170, 380))
    due = issue + timedelta(days=30)
    late = rng.randint(0, 20)
    return {
        "id": inv_id,
        "customer_id": customer_id,
        "amount": round(rng.uniform(800, 45_000), 2),
        "currency": CURRENCY,
        "issueDate": issue.isoformat(),
        "dueDate": due.isoformat(),
        "paidDate": (due + timedelta(days=late)).isoformat(),
        "daysLate": late,
        "status": "paid",
    }


def overdue_invoice(rng: random.Random, inv_id: str, customer_id: str, days_late: int) -> dict:
    due = AS_OF - timedelta(days=days_late)
    return {
        "id": inv_id,
        "customer_id": customer_id,
        "amount": round(rng.uniform(800, 45_000), 2),
        "currency": CURRENCY,
        "issueDate": (due - timedelta(days=30)).isoformat(),
        "dueDate": due.isoformat(),
        "paidDate": "",
        "daysLate": days_late,
        "status": "overdue",
    }


def make_invoices(rng: random.Random, customers: list[dict], cohorts: dict) -> list[dict]:
    invoices = []
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"INV-{counter:04d}"

    risky = set(cohorts["risky"])
    similar = set(cohorts["similar"])
    needs_overdue = set(cohorts["at_risk"]) - risky  # Q6 accounts not already in Q5
    for customer in customers:
        cid = customer["id"]
        n = rng.randint(4, 8)
        if cid in risky or cid in similar:
            # Older, settled history first; the last three (by dueDate) are all
            # late. Risky customers exceed the 60-day threshold (Q5); similar
            # customers stay just below it, the GDS plant that puts them near
            # the risky cohort in feature space without satisfying the rule.
            late_range = range(65, 121) if cid in risky else range(40, LATE_DAYS_THRESHOLD)
            for _ in range(n - 3):
                invoices.append(settled_invoice(rng, next_id(), cid))
            for days_late in sorted(rng.sample(late_range, 3), reverse=True):
                invoices.append(overdue_invoice(rng, next_id(), cid, days_late))
        else:
            for _ in range(n):
                invoices.append(normal_invoice(rng, next_id(), cid))
            if cid in needs_overdue:
                invoices.append(overdue_invoice(rng, next_id(), cid, rng.randint(20, 55)))
    return invoices


def make_payments(invoices: list[dict]) -> list[dict]:
    payments = []
    for invoice in invoices:
        if invoice["status"] == "paid":
            payments.append({
                "id": f"PAY-{len(payments) + 1:04d}",
                "invoice_id": invoice["id"],
                "amount": invoice["amount"],
                "date": invoice["paidDate"],
            })
    return payments


def make_revenue_entries(rng: random.Random) -> list[dict]:
    """Monthly reconciled revenue per BU, plus planted unreconciled amounts.

    The two BUs in UNRECONCILED_BUS get unreconciled totals above the
    materiality threshold; the rest stay well below it.
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
            "period": period,
            "amount": round(amount, 2),
            "currency": CURRENCY,
            "reconciled": str(reconciled).lower(),
        })

    for bu in BUSINESS_UNITS:
        for period in periods:
            add(bu["id"], period, rng.uniform(200_000, 900_000), True)
        if bu["id"] in UNRECONCILED_BUS:
            for _ in range(3):
                add(bu["id"], rng.choice(periods[-4:]), rng.uniform(45_000, 85_000), False)
        else:
            for _ in range(rng.randint(1, 2)):
                add(bu["id"], rng.choice(periods[-4:]), rng.uniform(8_000, 25_000), False)
    return entries


def make_findings(rng: random.Random, customers: list[dict], cohorts: dict) -> list[dict]:
    findings = []

    def add(customer_id: str, finding_type: str, status: str) -> None:
        opened = AS_OF - timedelta(days=rng.randint(15, 200))
        findings.append({
            "id": f"CF-{len(findings) + 1:03d}",
            "customer_id": customer_id,
            "type": finding_type,
            "status": status,
            "openedDate": opened.isoformat(),
        })

    for cid in cohorts["kyc"]:  # Q2, includes at_risk[0]
        for _ in range(rng.randint(1, 2)):
            add(cid, "KYC", "open")
    for cid in cohorts["at_risk"][1:]:  # Q6 open-finding condition without joining Q2
        add(cid, "AML", "open")

    strategic = set(cohorts["strategic"])
    non_strategic = [c["id"] for c in customers if c["id"] not in strategic]
    for cid in rng.sample(non_strategic, 4):
        add(cid, "AML", "open")
    for cid in rng.sample([c["id"] for c in customers], 8):
        add(cid, rng.choice(["KYC", "AML", "sanctions"]), "closed")
    return findings


def evaluate_questions(
    customers: list[dict],
    suppliers: list[dict],
    invoices: list[dict],
    revenue_entries: list[dict],
    findings: list[dict],
    classified_as: list[dict],
) -> dict:
    """Recompute all six answers from the generated rows (not the plant lists)."""
    by_id = {c["id"]: c for c in customers}
    bu_names = {bu["id"]: bu["name"] for bu in BUSINESS_UNITS}

    unreconciled: dict[str, float] = {}
    for entry in revenue_entries:
        if entry["reconciled"] == "false":
            unreconciled[entry["business_unit_id"]] = (
                unreconciled.get(entry["business_unit_id"], 0) + entry["amount"]
            )
    q1 = sorted(
        (
            {"business_unit_id": bu, "name": bu_names[bu], "unreconciled_total": round(total, 2),
             "threshold": MATERIALITY_THRESHOLD}
            for bu, total in unreconciled.items()
            if total > MATERIALITY_THRESHOLD
        ),
        key=lambda r: r["unreconciled_total"],
        reverse=True,
    )

    open_kyc: dict[str, list[str]] = {}
    for finding in findings:
        if finding["type"] == "KYC" and finding["status"] == "open":
            open_kyc.setdefault(finding["customer_id"], []).append(finding["id"])
    q2 = [
        {"customer_id": cid, "name": by_id[cid]["name"], "open_kyc_findings": sorted(ids)}
        for cid, ids in sorted(open_kyc.items())
    ]

    platinum_ids = {
        row["entity_id"] for row in classified_as if row["term_id"] == "TERM-01"
    }
    q3 = sorted(
        (
            {"customer_id": cid, "name": by_id[cid]["name"], "upsellScore": by_id[cid]["upsellScore"]}
            for cid in platinum_ids
        ),
        key=lambda r: r["upsellScore"],
        reverse=True,
    )

    q4 = sorted(
        (
            {"supplier_id": s["id"], "name": s["name"], "riskScore": s["riskScore"],
             "threshold": SUPPLIER_RISK_THRESHOLD}
            for s in suppliers
            if s["riskScore"] >= SUPPLIER_RISK_THRESHOLD
        ),
        key=lambda r: r["riskScore"],
        reverse=True,
    )

    per_customer: dict[str, list[dict]] = {}
    for invoice in invoices:
        per_customer.setdefault(invoice["customer_id"], []).append(invoice)
    q5 = []
    for cid, rows in sorted(per_customer.items()):
        last_three = sorted(rows, key=lambda r: r["dueDate"], reverse=True)[:3]
        if len(last_three) == 3 and all(r["daysLate"] > LATE_DAYS_THRESHOLD for r in last_three):
            q5.append({
                "customer_id": cid,
                "name": by_id[cid]["name"],
                "last_three": [{"invoice_id": r["id"], "daysLate": r["daysLate"]} for r in last_three],
            })

    strategic_ids = {
        row["entity_id"] for row in classified_as if row["term_id"] == "TERM-02"
    }
    has_overdue = {i["customer_id"] for i in invoices if i["status"] == "overdue"}
    has_open_finding = {f["customer_id"] for f in findings if f["status"] == "open"}
    q6 = [
        {
            "customer_id": cid,
            "name": by_id[cid]["name"],
            "conditions": {
                "profitabilityTrend": "declining",
                "churnRisk": "high",
                "overdue_invoice": True,
                "open_compliance_finding": True,
            },
        }
        for cid in sorted(strategic_ids)
        if by_id[cid]["profitabilityTrend"] == "declining"
        and by_id[cid]["churnRisk"] == "high"
        and cid in has_overdue
        and cid in has_open_finding
    ]

    return {"q1": q1, "q2": q2, "q3": q3, "q4": q4, "q5": q5, "q6": q6}


TREND_SCALE = {"improving": 0.0, "stable": 0.5, "declining": 1.0}
CHURN_SCALE = {"low": 0.0, "medium": 0.5, "high": 1.0}


def add_payment_features(customers: list[dict], invoices: list[dict]) -> None:
    """Derive the per-customer payment-behavior features the GDS similarity angle uses."""
    per_customer: dict[str, list[dict]] = {}
    for invoice in invoices:
        per_customer.setdefault(invoice["customer_id"], []).append(invoice)
    for customer in customers:
        rows = per_customer[customer["id"]]
        customer["avgDaysLate"] = round(sum(r["daysLate"] for r in rows) / len(rows), 1)
        customer["overdueShare"] = round(
            sum(1 for r in rows if r["status"] == "overdue") / len(rows), 2
        )


def similarity_vector(customer: dict) -> tuple[float, float, float, float]:
    return (
        min(customer["avgDaysLate"] / 100.0, 1.0),
        customer["overdueShare"],
        CHURN_SCALE[customer["churnRisk"]],
        TREND_SCALE[customer["profitabilityTrend"]],
    )


def evaluate_gds(
    customers: list[dict],
    suppliers: list[dict],
    supplies: list[dict],
    cohorts: dict,
) -> dict:
    """Deterministic proxies for the two Phase 5 GDS answers.

    Exposure: average supplier risk per business unit. Similarity: distance to
    the risky-cohort centroid over the payment-behavior features. Plain
    arithmetic, so ground truth stays reproducible without running GDS.
    """
    by_supplier = {s["id"]: s for s in suppliers}
    bu_names = {bu["id"]: bu["name"] for bu in BUSINESS_UNITS}
    per_bu: dict[str, list[dict]] = {}
    for row in supplies:
        per_bu.setdefault(row["business_unit_id"], []).append(by_supplier[row["supplier_id"]])
    exposure = sorted(
        (
            {
                "business_unit_id": bu_id,
                "name": bu_names[bu_id],
                "supplier_count": len(sups),
                "avg_supplier_risk": round(sum(s["riskScore"] for s in sups) / len(sups), 1),
                "max_supplier_risk": max(s["riskScore"] for s in sups),
            }
            for bu_id, sups in per_bu.items()
        ),
        key=lambda r: r["avg_supplier_risk"],
        reverse=True,
    )

    by_id = {c["id"]: c for c in customers}
    vectors = {c["id"]: similarity_vector(c) for c in customers}
    risky_vectors = [vectors[cid] for cid in cohorts["risky"]]
    centroid = [sum(dim) / len(risky_vectors) for dim in zip(*risky_vectors)]

    def distance(cid: str) -> float:
        return sum((a - b) ** 2 for a, b in zip(vectors[cid], centroid)) ** 0.5

    risky = set(cohorts["risky"])
    nearest = sorted((c["id"] for c in customers if c["id"] not in risky), key=distance)
    similarity = [
        {
            "customer_id": cid,
            "name": by_id[cid]["name"],
            "avgDaysLate": by_id[cid]["avgDaysLate"],
            "overdueShare": by_id[cid]["overdueShare"],
            "churnRisk": by_id[cid]["churnRisk"],
            "profitabilityTrend": by_id[cid]["profitabilityTrend"],
            "distance_to_risky_centroid": round(distance(cid), 3),
        }
        for cid in nearest[:N_SIMILAR]
    ]
    return {"exposure": exposure, "similarity": similarity}


def check_planted_gds(gds: dict, cohorts: dict) -> None:
    """Fail fast if the GDS plants drift from the recomputed proxies."""
    top, runner_up = gds["exposure"][0], gds["exposure"][1]
    assert top["business_unit_id"] == EXPOSURE_BU
    assert top["max_supplier_risk"] < SUPPLIER_RISK_THRESHOLD
    assert top["avg_supplier_risk"] > runner_up["avg_supplier_risk"]
    assert {r["customer_id"] for r in gds["similarity"]} == set(cohorts["similar"])


def check_planted(answers: dict, cohorts: dict, customers: list[dict]) -> None:
    """Fail fast if the recomputed answers drift from the planted cohorts."""
    assert {r["business_unit_id"] for r in answers["q1"]} == set(UNRECONCILED_BUS)
    assert {r["customer_id"] for r in answers["q2"]} == set(cohorts["kyc"])
    assert {r["customer_id"] for r in answers["q3"]} == set(cohorts["platinum"])
    scores = [r["upsellScore"] for r in answers["q3"]]
    assert len(scores) == len(set(scores)), "upsell scores must be distinct"
    top_three = sorted(customers, key=lambda c: c["upsellScore"], reverse=True)[:3]
    assert all(c["segment"] == "platinum" for c in top_three), "top-3 upsell must be platinum"
    assert len(answers["q4"]) == N_HIGH_RISK_SUPPLIERS
    assert {r["customer_id"] for r in answers["q5"]} == set(cohorts["risky"])
    assert {r["customer_id"] for r in answers["q6"]} == set(cohorts["at_risk"])


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

    customers, cohorts = make_customers(rng)
    suppliers = make_suppliers(rng)
    invoices = make_invoices(rng, customers, cohorts)
    payments = make_payments(invoices)
    revenue_entries = make_revenue_entries(rng)
    findings = make_findings(rng, customers, cohorts)
    add_payment_features(customers, invoices)

    belongs_to = [
        {"customer_id": c["id"], "business_unit_id": rng.choice(BUSINESS_UNITS)["id"]}
        for c in customers
    ]
    supplies = make_supplies(rng, suppliers)

    # Pre-planted classifications only: Platinum Customer and Strategic Account.
    # High-Risk Supplier and Risky Customer are computed live during the demo
    # and written back (the Multi-Hop Native moment).
    classified_as = [
        {
            "entity_id": cid,
            "term_id": "TERM-01",
            "reason": "segment = 'platinum' per Platinum Customer Rule",
            "evaluatedAt": EVALUATED_AT,
            "ruleVersion": RULE_VERSION,
        }
        for cid in cohorts["platinum"]
    ] + [
        {
            "entity_id": cid,
            "term_id": "TERM-02",
            "reason": "platinum segment and flagged strategic by account management",
            "evaluatedAt": EVALUATED_AT,
            "ruleVersion": RULE_VERSION,
        }
        for cid in cohorts["strategic"]
    ]

    realized_as = [
        {"edm_entity_id": "EDM-01", "instance_id": c["id"], "instance_label": "Customer"}
        for c in customers
    ] + [
        {"edm_entity_id": "EDM-04", "instance_id": i["id"], "instance_label": "Invoice"}
        for i in invoices
    ]

    answers = evaluate_questions(
        customers, suppliers, invoices, revenue_entries, findings, classified_as
    )
    check_planted(answers, cohorts, customers)
    gds = evaluate_gds(customers, suppliers, supplies, cohorts)
    check_planted_gds(gds, cohorts)

    print("Node CSVs:")
    write_csv("customers.csv",
              ["id", "name", "segment", "profitabilityTrend", "churnRisk", "upsellScore",
               "avgDaysLate", "overdueShare"], customers)
    write_csv("suppliers.csv", ["id", "name", "category", "riskScore"], suppliers)
    write_csv("business_units.csv", ["id", "name", "region"], BUSINESS_UNITS)
    write_csv("invoices.csv",
              ["id", "amount", "currency", "issueDate", "dueDate", "paidDate", "daysLate", "status"],
              invoices)
    write_csv("payments.csv", ["id", "amount", "date"], payments)
    write_csv("revenue_entries.csv",
              ["id", "period", "amount", "currency", "reconciled"], revenue_entries)
    write_csv("compliance_findings.csv", ["id", "type", "status", "openedDate"], findings)
    write_csv("edm_entities.csv", ["id", "name", "description"], EDM_ENTITIES)
    write_csv("business_terms.csv", ["id", "name", "definition"], BUSINESS_TERMS)
    write_csv("business_rules.csv",
              ["id", "name", "expression", "description", "threshold"], BUSINESS_RULES)
    write_csv("policies.csv", ["id", "name", "type"], POLICIES)
    write_csv("thresholds.csv", ["id", "name", "value", "currency"], THRESHOLDS)
    write_csv("data_sources.csv", ["id", "name", "system", "table"], DATA_SOURCES)

    print("Relationship CSVs:")
    write_csv("has_invoice.csv", ["customer_id", "invoice_id"],
              [{"customer_id": i["customer_id"], "invoice_id": i["id"]} for i in invoices])
    write_csv("settled_by.csv", ["invoice_id", "payment_id"],
              [{"invoice_id": p["invoice_id"], "payment_id": p["id"]} for p in payments])
    write_csv("belongs_to.csv", ["customer_id", "business_unit_id"], belongs_to)
    write_csv("recognizes.csv", ["business_unit_id", "revenue_entry_id"],
              [{"business_unit_id": r["business_unit_id"], "revenue_entry_id": r["id"]}
               for r in revenue_entries])
    write_csv("supplies.csv", ["supplier_id", "business_unit_id"], supplies)
    write_csv("has_finding.csv", ["customer_id", "finding_id"],
              [{"customer_id": f["customer_id"], "finding_id": f["id"]} for f in findings])
    write_csv("classified_as.csv",
              ["entity_id", "term_id", "reason", "evaluatedAt", "ruleVersion"], classified_as)
    write_csv("defined_by.csv", ["term_id", "rule_id"], DEFINED_BY)
    write_csv("evaluates.csv", ["rule_id", "edm_entity_id"], EVALUATES)
    write_csv("constrains.csv", ["policy_id", "edm_entity_id"], CONSTRAINS)
    write_csv("applies_to.csv", ["threshold_id", "term_id"], APPLIES_TO)
    write_csv("maps_to.csv", ["edm_entity_id", "data_source_id"], MAPS_TO)
    write_csv("realized_as.csv", ["edm_entity_id", "instance_id", "instance_label"], realized_as)

    ground_truth = {
        "schema_version": 1,
        "seed": SEED,
        "as_of_date": AS_OF.isoformat(),
        "summary": {
            "customers": len(customers),
            "suppliers": len(suppliers),
            "business_units": len(BUSINESS_UNITS),
            "invoices": len(invoices),
            "payments": len(payments),
            "revenue_entries": len(revenue_entries),
            "compliance_findings": len(findings),
            "answers": {q: len(rows) for q, rows in answers.items()},
        },
        "q1_unreconciled_business_units": answers["q1"],
        "q2_kyc_violators": answers["q2"],
        "q3_platinum_by_upsell": answers["q3"],
        "q4_high_risk_suppliers": answers["q4"],
        "q5_risky_customers": answers["q5"],
        "q6_strategic_at_risk": answers["q6"],
        "gds_q4_exposed_business_unit": EXPOSURE_BU,
        "gds_q4_supplier_exposure_by_business_unit": gds["exposure"],
        "gds_q5_similarity_candidates": gds["similarity"],
    }
    gt_path = DATA_DIR / "ground_truth.json"
    gt_path.write_text(json.dumps(ground_truth, indent=2) + "\n")
    print(f"  ground_truth.json: answers {ground_truth['summary']['answers']}")
    print(f"  gds: exposed BU {EXPOSURE_BU}, "
          f"{len(gds['similarity'])} similarity candidates")


if __name__ == "__main__":
    main()
