"""
Finance Genie — Synthetic Fraud Dataset Generator (v2)

25,000 accounts across 10 structured fraud rings designed to expose
the three gaps described in genie-demo.md:

  accounts.csv        25,000 rows  Bank accounts with KYC attributes
  customers.csv       25,000 rows  Customer identity (phone, email, address)
  merchants.csv        7,500 rows  Merchants with category and risk tier
  transactions.csv   250,000 rows  Account -> Merchant transactions
  account_links.csv  300,000 rows  Peer-to-peer account transfers

Fraud design principles:
  TABULAR signals are deliberately weak so Genie cannot separate fraud
  from normal on any single column.

  GRAPH signals are strong and correspond 1:1 to the three GDS algorithms:

  PageRank  — 200 normal "whale" accounts dominate raw P2P inbound count.
               Genie's sort-by-volume answer names whales, not the ring.
               PageRank elevates ring members because they receive from
               other high-PR ring nodes, not from peripheral accounts.

  Louvain   — 10 rings of ~100 accounts each.  Within-ring P2P links
               create dense communities.  Individual bilateral pair counts
               stay low (1-3), so Genie's pair-grouping misses the ring.
               Louvain assigns every ring member a shared community_id.

  NodeSim   — Each ring has 4 shared "anchor" high-risk merchants.  Ring
               members share those specific merchants → high intra-ring
               Jaccard.  Overall high-risk fraction is nearly the same for
               fraud and normal, so a column filter cannot find them.

All constants are loaded from config.py, which reads ../.env.
Copy ../.env.sample to ../.env to override defaults. See worklog/strengthen_plan.md
for per-phase tuning values.

Usage:
    From the enrichment-pipeline/ directory (which contains pyproject.toml):
        uv run setup/generate_data.py                 # writes to finance-genie/data/
        uv run setup/generate_data.py --output ./data/
"""

import argparse
import hashlib
import json
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path

from faker import Faker

fake = Faker()
fake.seed_instance(42)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from checks_structural import build_ring_index
from config import (
    SEED,
    NUM_ACCOUNTS,
    NUM_MERCHANTS,
    NUM_TXN,
    NUM_P2P,
    FRAUD_RATE,
    N_RINGS,
    WITHIN_RING_PROB,
    WHALE_RATE,
    WHALE_INBOUND,
    RING_ANCHOR_PREF,
)

WHALE_OUTBOUND = WHALE_INBOUND
WHALE_RECIPIENT_POOL_SIZE = 30
RING_ANCHOR_CNT = 4
CAPTAIN_COUNT = 5
# Kept below whale inbound (~210) so naive inbound-sort finds whales, not
# captains. Above ~0.10 captains breach the top-200 inbound and break the
# whale-hiding property.
CAPTAIN_TRANSFER_PROB = 0.02
FRAUD_LOGNORM_MU = 4.1
FRAUD_LOGNORM_SIGMA = 1.2
NORMAL_LOGNORM_MU = 4.0
NORMAL_LOGNORM_SIGMA = 1.2
P2P_LOGNORM_MU = 5.0
P2P_LOGNORM_SIGMA = 1.5

# KYC story ring (two-layer data model, layer 1). Hand-designed shared
# identifiers inside one existing fraud ring: two shared phones cover 4
# accounts each, one shared address spans both phone groups so the identity
# graph connects all 8 members. The 555 exchange is reserved for story data;
# background phones never use it (see _background_phone).
KYC_STORY_RING_ID = 0
KYC_STORY_RING_SIZE = 8
KYC_STORY_PHONES = ("312-555-0142", "312-555-0143")
KYC_STORY_ADDRESS = "1247 W Cermak Rd, Chicago, IL 60608"


# ── Helpers ───────────────────────────────────────────────────────────

def _build_rings(num_accounts: int, fraud_rate: float, n_rings: int):
    """Partition fraud accounts into n_rings evenly-sized sets."""
    total_fraud = int(num_accounts * fraud_rate)
    ring_size   = total_fraud // n_rings
    remainder   = total_fraud % n_rings

    all_ids = list(range(1, num_accounts + 1))
    random.shuffle(all_ids)

    rings, start = [], 0
    for r in range(n_rings):
        size = ring_size + (1 if r < remainder else 0)
        rings.append(set(all_ids[start : start + size]))
        start += size

    return rings, set().union(*rings)


def build_ground_truth():
    """Reconstruct rings, fraud_ids, and whale_ids from the seeded RNG.

    Must be called immediately after random.seed(SEED) and before any other
    RNG-consuming step. Both generate_all() and the verification script call
    this so they see identical ring and whale identities.
    """
    rings, fraud_ids = _build_rings(NUM_ACCOUNTS, FRAUD_RATE, N_RINGS)
    normal_ids       = set(range(1, NUM_ACCOUNTS + 1)) - fraud_ids
    whale_ids        = set(random.sample(list(normal_ids), int(NUM_ACCOUNTS * WHALE_RATE)))
    return rings, fraud_ids, whale_ids


def _build_whale_recipient_pools(
    whale_ids: set,
    fraud_ids: set,
    pool_size: int,
) -> dict:
    """Assign each whale a fixed pool of recurring outbound recipients.

    Recipients are sampled exclusively from plain normal accounts — not whales,
    not ring members.  This keeps recipients low-degree so their PageRank stays
    low, preserving the sender-peripherality property: whale outbound goes to
    unimportant accounts, so PageRank does not compound through the whale the
    way it does through the ring.

    Returns a dict mapping whale_id -> list of recipient account_ids.
    """
    eligible = sorted(set(range(1, NUM_ACCOUNTS + 1)) - whale_ids - fraud_ids)
    pool_size = min(pool_size, len(eligible))
    return {whale: random.sample(eligible, pool_size) for whale in whale_ids}


def kyc_story_assignments(rings: list) -> tuple[list[int], dict, dict]:
    """Return (members, phone→accounts, address→accounts) for the KYC story ring.

    Pure function of the ring partition — consumes no RNG, so it can be called
    from both the generator and the verifier without perturbing the seeded
    stream. Members are the first KYC_STORY_RING_SIZE accounts of the story
    ring in sorted order.
    """
    members = sorted(rings[KYC_STORY_RING_ID])[:KYC_STORY_RING_SIZE]
    half = KYC_STORY_RING_SIZE // 2
    phone_map = {
        KYC_STORY_PHONES[0]: members[:half],
        KYC_STORY_PHONES[1]: members[half:],
    }
    address_map = {KYC_STORY_ADDRESS: members[half // 2 : half // 2 + half]}
    return members, phone_map, address_map


# ── Generators ────────────────────────────────────────────────────────

def generate_accounts() -> pd.DataFrame:
    account_types = ["checking", "savings", "business"]
    regions       = ["US-East", "US-West", "US-Central", "EU-West", "EU-East", "APAC"]
    base_date     = datetime(2018, 1, 1)

    rows = []
    for i in range(1, NUM_ACCOUNTS + 1):
        open_date = base_date + timedelta(days=random.randint(0, 1800))
        account_type = random.choice(account_types)
        # Business accounts get a company name; personal accounts (checking,
        # savings) get a person name. Faker draws from its own seeded RNG
        # (fake.seed_instance), so this does not perturb the global `random`
        # stream that builds the ring / fraud / whale ground truth.
        account_name = (
            fake.company() if account_type == "business" else fake.name()
        )
        rows.append({
            "account_id":   i,
            "account_hash": hashlib.md5(f"acct-{i}".encode()).hexdigest()[:12],
            "account_name": account_name,
            "account_type": account_type,
            "region":       random.choice(regions),
            "balance":      round(random.uniform(100, 500_000), 2),
            "opened_date":  open_date.strftime("%Y-%m-%d"),
            "holder_age":   random.randint(18, 80),
        })
    return pd.DataFrame(rows)


def generate_customers(accounts_df: pd.DataFrame, rings: list) -> pd.DataFrame:
    """Generate one customer per account with phone, email, and address.

    Two-layer model: the KYC story ring members get the hand-designed shared
    identifiers; every other customer (background layer) gets identifiers that
    are unique across the dataset and can never collide with story values.
    """
    _, phone_map, address_map = kyc_story_assignments(rings)
    story_phone   = {a: p for p, accts in phone_map.items() for a in accts}
    story_address = {a: addr for addr, accts in address_map.items() for a in accts}

    seen_phones = set(phone_map)

    def _background_phone() -> str:
        # NANP format. The 555 exchange is reserved for story data, so a
        # background customer can never share a story phone.
        while True:
            exchange = random.randint(200, 999)
            if exchange == 555:
                continue
            phone = f"{random.randint(200, 989)}-{exchange}-{random.randint(0, 9999):04d}"
            if phone not in seen_phones:
                seen_phones.add(phone)
                return phone

    def _background_address() -> str:
        # fake.unique guarantees a distinct street per customer; the story
        # address is excluded explicitly in case Faker ever produces it.
        while True:
            addr = (
                f"{fake.unique.street_address()}, {fake.city()}, "
                f"{fake.state_abbr()} {fake.zipcode()}"
            )
            if addr not in address_map:
                return addr

    rows = []
    for acct in accounts_df.itertuples():
        rows.append({
            "customer_id":   acct.account_id,
            "account_id":    acct.account_id,
            "customer_name": acct.account_name,
            "phone":         story_phone.get(acct.account_id) or _background_phone(),
            "email":         fake.unique.email(),
            "address":       story_address.get(acct.account_id) or _background_address(),
        })
    return pd.DataFrame(rows)


def generate_account_labels(fraud_ids: set) -> pd.DataFrame:
    rows = [{"account_id": i, "is_fraud": i in fraud_ids} for i in range(1, NUM_ACCOUNTS + 1)]
    return pd.DataFrame(rows)


def generate_merchants() -> pd.DataFrame:
    categories = ["retail", "online", "restaurant", "travel",
                  "crypto", "gaming", "grocery", "utilities"]
    regions    = ["US-East", "US-West", "US-Central", "EU-West", "EU-East", "APAC"]

    rows = []
    for i in range(1, NUM_MERCHANTS + 1):
        rows.append({
            "merchant_id":   i,
            "merchant_name": fake.unique.company(),
            "category":      random.choice(categories),
            "region":        random.choice(regions),
        })
    return pd.DataFrame(rows)


def generate_transactions(
    fraud_ids: set,
    rings: list,
    merchants_df: pd.DataFrame,
    ring_anchors: dict,          # ring_idx -> [merchant_id, ...]
) -> pd.DataFrame:
    all_ids   = merchants_df["merchant_id"].tolist()
    base_date = datetime(2024, 1, 1)

    acct_to_ring = build_ring_index(rings)

    rows = []
    for txn_id in range(1, NUM_TXN + 1):
        acct_id  = random.randint(1, NUM_ACCOUNTS)
        is_fraud = acct_id in fraud_ids

        # Merchant selection:
        # Fraud accounts use their ring's anchor merchants RING_ANCHOR_PREF of the
        # time. The anchors are picked from high-risk merchants, but the overall
        # high-risk fraction for fraud vs normal stays within ~3 pp — not enough
        # for Genie to separate on a merchant-tier filter.
        if is_fraud and random.random() < RING_ANCHOR_PREF:
            merch_id = random.choice(ring_anchors[acct_to_ring[acct_id]])
        else:
            merch_id = random.choice(all_ids)

        # Amount and hour: extremely subtle shift.
        # Lognormal distributions overlap heavily; tabular models
        # cannot cleanly separate fraud from normal on these columns alone.
        if is_fraud:
            amount = round(random.lognormvariate(FRAUD_LOGNORM_MU, FRAUD_LOGNORM_SIGMA), 2)
            hour   = random.choices(range(24), weights=[2]*6 + [3]*12 + [2]*6)[0]
        else:
            amount = round(random.lognormvariate(NORMAL_LOGNORM_MU, NORMAL_LOGNORM_SIGMA), 2)
            hour   = random.choices(range(24), weights=[1]*6 + [4]*12 + [2]*6)[0]

        ts = base_date + timedelta(
            days=random.randint(0, 89),
            hours=hour,
            minutes=random.randint(0, 59),
        )
        rows.append({
            "txn_id":        txn_id,
            "account_id":    acct_id,
            "merchant_id":   merch_id,
            "amount":        amount,
            "txn_timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
            "txn_hour":      hour,
        })
    return pd.DataFrame(rows)


def build_ground_truth_json(
    rings: list,
    fraud_ids: set,
    whale_ids: set,
    ring_anchors: dict,
    merchants_df: "pd.DataFrame",
) -> dict:
    """Return a ground-truth dict suitable for JSON serialisation.

    Written to ground_truth.json alongside the CSVs so a presenter can
    check Genie query results against the known ring membership, whale list,
    and per-ring anchor merchants without opening any CSV.
    """
    merch_lookup = (
        merchants_df.set_index("merchant_id")[["category"]]
        .to_dict("index")
    )
    kyc_members, kyc_phone_map, kyc_address_map = kyc_story_assignments(rings)
    return {
        "schema_version": 1,
        "seed": SEED,
        "summary": {
            "total_rings":          len(rings),
            "total_fraud_accounts": len(fraud_ids),
            "total_whale_accounts": len(whale_ids),
            "anchor_merchants_per_ring": len(next(iter(ring_anchors.values()))) if ring_anchors else 0,
        },
        "rings": [
            {
                "ring_id":         i,
                "account_ids":     sorted(ring),
                "anchor_merchants": [
                    {
                        "merchant_id": mid,
                        "category":    merch_lookup[mid]["category"],
                    }
                    for mid in ring_anchors[i]
                ],
            }
            for i, ring in enumerate(rings)
        ],
        "whale_account_ids": sorted(whale_ids),
        "kyc_story_ring": {
            "ring_id":        KYC_STORY_RING_ID,
            "account_ids":    kyc_members,
            "shared_phones":  kyc_phone_map,
            "shared_address": kyc_address_map,
        },
    }


def _random_account_other_than(exclude: int) -> int:
    acct = random.randint(1, NUM_ACCOUNTS)
    while acct == exclude:
        acct = random.randint(1, NUM_ACCOUNTS)
    return acct


def _pick_within_ring_transfer(
    rings: list,
    ring_captain_lists: list[list[int]],
) -> tuple[int, int]:
    ring_idx  = random.randrange(len(rings))
    ring_list = list(rings[ring_idx])
    captains  = ring_captain_lists[ring_idx]

    if captains and random.random() < CAPTAIN_TRANSFER_PROB:
        dst = random.choice(captains)
        src = random.choice([a for a in ring_list if a != dst])
    else:
        src, dst = random.sample(ring_list, 2)
    return src, dst


def _pick_whale_inbound_transfer(whale_list: list[int]) -> tuple[int, int]:
    dst = random.choice(whale_list)
    return _random_account_other_than(dst), dst


def _pick_whale_outbound_transfer(
    whale_list: list[int],
    whale_recipient_pools: dict,
) -> tuple[int, int]:
    src = random.choice(whale_list)
    dst = random.choice(whale_recipient_pools[src])
    return src, dst


def _pick_random_transfer() -> tuple[int, int]:
    src = random.randint(1, NUM_ACCOUNTS)
    return src, _random_account_other_than(src)


def generate_account_links(
    rings: list,
    whale_ids: set,
    whale_recipient_pools: dict,
) -> pd.DataFrame:
    """Generate peer-to-peer transfer links.

    whale_recipient_pools maps each whale ID to its pre-assigned list of
    recurring recipients. Using a fixed pool makes whales resemble a payment
    aggregator (consistent counterparties) rather than a pure collection
    account.
    """
    whale_list = list(whale_ids)
    base_date  = datetime(2024, 1, 1)

    # Pre-assign captains for each ring. Captains are the primary inbound
    # targets for CAPTAIN_TRANSFER_PROB of within-ring transfers, concentrating
    # PageRank on a small set of high-degree nodes so ring members surface in
    # the top-20 by risk_score.
    ring_captain_lists = [
        random.sample(list(ring), min(CAPTAIN_COUNT, len(ring)))
        for ring in rings
    ]

    rows = []
    for link_id in range(1, NUM_P2P + 1):
        r = random.random()

        if r < WITHIN_RING_PROB:
            src, dst = _pick_within_ring_transfer(rings, ring_captain_lists)
        elif r < WITHIN_RING_PROB + WHALE_INBOUND:
            src, dst = _pick_whale_inbound_transfer(whale_list)
        elif r < WITHIN_RING_PROB + WHALE_INBOUND + WHALE_OUTBOUND:
            src, dst = _pick_whale_outbound_transfer(whale_list, whale_recipient_pools)
        else:
            src, dst = _pick_random_transfer()

        amount = round(random.lognormvariate(P2P_LOGNORM_MU, P2P_LOGNORM_SIGMA), 2)
        ts = base_date + timedelta(
            days=random.randint(0, 89),
            hours=random.randint(0, 23),
            minutes=random.randint(0, 59),
        )
        rows.append({
            "link_id":            link_id,
            "src_account_id":     src,
            "dst_account_id":     dst,
            "amount":             amount,
            "transfer_timestamp": ts.strftime("%Y-%m-%d %H:%M:%S"),
        })
    return pd.DataFrame(rows)


# ── Orchestrator ──────────────────────────────────────────────────────

def generate_all(output_dir: Path) -> dict:
    """Generate all five tables and write them as CSV files to output_dir."""
    random.seed(SEED)
    output_dir.mkdir(parents=True, exist_ok=True)

    rings, fraud_ids, whale_ids = build_ground_truth()

    print("Generating accounts ...")
    accounts_df = generate_accounts()
    accounts_df.to_csv(output_dir / "accounts.csv", index=False)
    print(f"  accounts: {len(accounts_df):,}  |  fraud rings: {N_RINGS} × ~{len(fraud_ids)//N_RINGS}  "
          f"|  whale hubs: {len(whale_ids)}")

    print("Generating account labels ...")
    labels_df = generate_account_labels(fraud_ids)
    labels_df.to_csv(output_dir / "account_labels.csv", index=False)
    print(f"  account_labels: {len(labels_df):,}  |  fraud: {labels_df['is_fraud'].sum()}")

    print("Generating merchants ...")
    merchants_df = generate_merchants()
    merchants_df.to_csv(output_dir / "merchants.csv", index=False)

    # Assign anchor merchants to each ring after merchants are generated.
    # Anchors are sampled from ALL merchants. The structural signal comes from
    # shared SPECIFIC merchants, not from any merchant attribute — a column
    # filter cannot find the fraud ring.
    all_merchant_ids = merchants_df["merchant_id"].tolist()
    ring_anchors     = {
        ring_idx: random.sample(all_merchant_ids, RING_ANCHOR_CNT)
        for ring_idx in range(N_RINGS)
    }
    print(f"  merchants: {len(merchants_df):,}  |  anchor merchants/ring: {RING_ANCHOR_CNT}")

    print("Writing ground truth ...")
    gt = build_ground_truth_json(rings, fraud_ids, whale_ids, ring_anchors, merchants_df)
    (output_dir / "ground_truth.json").write_text(json.dumps(gt, indent=2))
    ring_sizes = [len(r) for r in rings]
    print(f"  ground_truth.json: {N_RINGS} rings × ~{sum(ring_sizes)//N_RINGS} accounts, "
          f"{len(whale_ids)} whales, {RING_ANCHOR_CNT} anchors/ring")

    print("Generating transactions ...")
    txn_df = generate_transactions(fraud_ids, rings, merchants_df, ring_anchors)
    txn_df.to_csv(output_dir / "transactions.csv", index=False)
    print(f"  transactions: {len(txn_df):,}")

    print("Generating account links ...")
    whale_recipient_pools = _build_whale_recipient_pools(
        whale_ids, fraud_ids, WHALE_RECIPIENT_POOL_SIZE
    )
    links_df = generate_account_links(rings, whale_ids, whale_recipient_pools)
    links_df.to_csv(output_dir / "account_links.csv", index=False)
    print(
        f"  account_links: {len(links_df):,}  |  "
        f"whale outbound: fixed pool ({WHALE_RECIPIENT_POOL_SIZE} recipients/whale)"
    )

    # Customers are generated LAST so the extra RNG consumption cannot shift
    # the seeded stream that produces every table above — all pre-KYC outputs
    # stay byte-identical to what earlier generator versions produced.
    print("Generating customers ...")
    customers_df = generate_customers(accounts_df, rings)
    customers_df.to_csv(output_dir / "customers.csv", index=False)
    print(
        f"  customers: {len(customers_df):,}  |  KYC story ring: "
        f"{KYC_STORY_RING_SIZE} accounts, {len(KYC_STORY_PHONES)} shared phones, "
        f"1 shared address"
    )

    return {
        "accounts":        len(accounts_df),
        "customers":       len(customers_df),
        "account_labels":  len(labels_df),
        "merchants":       len(merchants_df),
        "transactions":    len(txn_df),
        "account_links":   len(links_df),
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate synthetic fraud dataset as CSV files."
    )
    parser.add_argument(
        "--output",
        default=Path(__file__).resolve().parents[2] / "data",
        help="Output directory for CSV files (default: finance-genie/data/)",
    )
    args   = parser.parse_args()
    output = Path(args.output)
    print(f"Writing CSV files to: {output.resolve()}")
    counts = generate_all(output)
    print(f"\nDone. {sum(counts.values()):,} total rows written to {output.resolve()}/")
