# Proposal: Add live operational graph evidence to the demo

## Goal

Add a live, read-only view of the Finance Genie operational graph to the demo.
The demo should show graph evidence beside the semantic catalog context. It
should not copy operational graph data into the semantic Neo4j store.

## Why add it

The current demo explains what a business concept means and where its data
lives. It can list the related tables, columns, graph labels, and graph paths.
It cannot show the current accounts and relationships that support an
investigation.

Live graph evidence would answer two connected questions:

- **Meaning:** What does shared identity, transfer exposure, or high risk mean?
- **Evidence:** Which current graph entities and relationships support that
  meaning?

## Recommended design

Keep two Neo4j databases with separate purposes:

- **Semantic store:** Holds catalog metadata, business concepts, and mappings.
- **Operational graph:** Holds the Finance Genie accounts, customers,
  identities, transfers, and graph results created by `make demo`.

The demo should query the operational graph when it needs evidence. The demo
should return a small, structured result. It should not copy operational nodes,
relationships, or property values into the semantic store.

The demo should first use the semantic store to identify the correct concept and
source fields. It should then use a dedicated read-only graph connection to get
the supporting operational graph evidence.

## Assumptions

- **Demo data:** The parent Finance Genie demo setup has created and loaded the
  operational graph.
- **Access:** The demo has separate read-only credentials for the operational
  graph.
- **Scope:** The first release supports the existing shared-identity,
  transfer-exposure, fraud-ring, and high-risk concepts.
- **Data handling:** The response returns only the fields needed for the demo.
  It does not return phone numbers, addresses, or other sensitive values.

## Risks and controls

- **Data boundary risk:** A shared connection could write operational data into
  the semantic store. Use separate connection settings and reject operational
  labels in the semantic store.
- **Permission risk:** A broad Neo4j account could change the graph. Give the
  demo a read-only operational-graph account.
- **Privacy risk:** A graph path may expose sensitive values. Return stable
  identifiers, counts, relationship types, and derived scores. Exclude phone
  numbers and addresses.
- **Performance risk:** Broad graph searches may be slow. Require an account
  ID, identity cluster ID, or another narrow starting value. Set result limits
  and timeouts.
- **Consistency risk:** Databricks and Neo4j may update at different times. Show
  the graph data time and explain that the result is current graph evidence.
- **Demo reliability risk:** The operational graph may be unavailable. Return a
  clear message and keep the semantic catalog tools available.

## Delivery checklist

### 1. Define the evidence contract

**Status:** Pending

- List the investigation questions that need live graph evidence.
- Define the required input for each question.
- Define the smallest useful result for each question.
- Approve the fields that may appear in a demo response.
- Define limits for rows, paths, and execution time.

**Completion criteria:** Each supported question has a written input, result,
and privacy boundary.

### 2. Add a separate read-only graph connection

**Status:** Pending

- Create a dedicated read-only account for the operational graph.
- Store its connection details separately from the semantic-store settings.
- Confirm that the account cannot create, update, or delete graph data.
- Confirm that the semantic store still rejects operational graph labels.

**Completion criteria:** The demo can read the operational graph and cannot
write to it or use it as the semantic store.

### 3. Build the graph-evidence lookup

**Status:** Pending

- Add one lookup for shared identity.
- Add one lookup for transfer exposure.
- Add one lookup for fraud-ring evidence.
- Add one lookup for high-risk evidence.
- Return structured results with clear source labels and no sensitive values.

**Completion criteria:** Each lookup returns the expected graph evidence for a
known Finance Genie fixture.

### 4. Combine catalog context and graph evidence

**Status:** Pending

- Start each demo response with the business concept and its definition.
- Show the related Databricks tables and columns.
- Show the matching graph labels, relationship types, and live evidence.
- Label derived signals as investigation evidence rather than a fraud decision.

**Completion criteria:** One response explains both the meaning of a concept
and the graph evidence for a known fixture.

### 5. Add validation and demo coverage

**Status:** Pending

- Check that each lookup uses only read-only graph access.
- Check that responses exclude sensitive property values.
- Check that result limits and timeouts work.
- Check that the semantic store contains no operational graph data.
- Add a demo scenario for a known shared-identity cluster.
- Add a clear failure message for an unavailable operational graph.

**Completion criteria:** Automated checks pass, the demo shows one complete
investigation path, and the data boundary remains intact.

## Final result

The demo will combine two forms of evidence. The semantic store will explain
what the data means. The operational graph will show the current relationships
that support the investigation. The two stores will remain separate.
