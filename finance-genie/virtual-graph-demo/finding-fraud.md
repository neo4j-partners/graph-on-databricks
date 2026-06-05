# Finding fraud with the Virtual Graph

A plain-English walkthrough for showing how the Finance Genie Virtual Graph finds
money laundering. Every query below has been tested on the Virtual Graph and comes
back in a few seconds. Copy and paste each one as written.

## The data in plain terms

Think of the data as a map of money moving between people and businesses.

- **Accounts** are people or businesses. Each one has a balance, the date it was
  opened, and the account holder's age.
- **A transfer** is one account sending money to another account. We write it as
  `TRANSFERRED_TO`. Every transfer records the amount and the time it happened.
- **Merchants** are shops and services. When an account pays a merchant we call it
  `TRANSACTED_WITH`, and it records the amount and the time.

That is the whole picture: accounts send money to each other, and accounts pay
merchants. Everything below is just "follow the money" across that map.

One practical note before we start. The sample data ends on 30 March 2024, so the
"recent activity" queries use a fixed cutoff date near the end of the data instead of
today's date. In a live system you would work the cutoff out from the current date.

## How a launderer moves money

Money laundering almost always moves through three stages. Each stage leaves a
different footprint in the data, and each query below is tuned to one footprint.

1. **Placement.** Get the dirty cash into the banking system without setting off
   alarms. Footprints: lots of transfers sized just under the reporting limit, and
   brand-new accounts that immediately start moving large sums.
2. **Layering.** Move the money around to blur where it came from. Footprints: the
   same money bouncing back and forth between two accounts, and accounts that push out
   far more money than they actually hold.
3. **Integration.** Bring the now-clean money back together and pull it out.
   Footprints: collection accounts that gather money from many senders, one account
   spraying money out to many others, and accounts that behave like couriers rather
   than real customers.

The demo follows these three stages in order.

## The demo script

Paste each query into your Cypher console against the Virtual Graph and read the rows
that come back. A few queries finish with a quick counting step you do on the results;
where that happens it is spelled out under the query in plain terms.

### Stage 1: Placement (getting the money in)

#### 1. Structuring: transfers kept just under the limit

Banks have to report large transfers, so launderers split a big sum into many
transfers sized just under the limit (here, between $9,000 and $9,999). This finds
every account ranked by how many just-under-the-limit transfers it sent. Runs in about
a second.

```cypher
MATCH (src:Account)-[t:TRANSFERRED_TO]->(:Account)
WHERE t.amount >= 9000 AND t.amount < 10000
WITH src.account_id AS account_id, count(t) AS near_threshold, round(sum(t.amount), 2) AS total
RETURN account_id, near_threshold, total
ORDER BY near_threshold DESC
```

Read it as: the accounts at the top are the ones most deliberately sitting just under
the radar. Each row is one account:

* `account_id`: the account that sent the transfers.
* `near_threshold`: how many of its transfers landed just under the limit, between
  $9,000 and $9,999. The number is a count of transfers, so a 2 means it sent two such
  transfers and a 1 means one.
* `total`: those just-under-the-limit transfers added up, in dollars.

#### 2. Busy brand-new accounts

Real customers ramp up slowly. An account opened days ago that is already pushing out
large sums is a red flag. This finds accounts opened in the last 30 days of the data
and totals how much they moved. Runs in about a second.

```cypher
MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account)
WHERE a.opened_date >= date("2022-11-06")
WITH a.account_id AS account_id, a.opened_date AS opened_date,
     a.holder_age AS holder_age, count(t) AS transfers, round(sum(t.amount), 2) AS outflow
RETURN account_id, opened_date, holder_age, transfers, outflow
ORDER BY outflow DESC
```

Read it as: brand-new accounts near the top of this list are already behaving like
established money movers. Each row is one account:

* `account_id`: the new account.
* `opened_date`: the day the account was opened.
* `holder_age`: the age of the person who owns it.
* `transfers`: how many transfers the account sent.
* `outflow`: the total dollars it sent out.

### Stage 2: Layering (hiding the trail)

#### 3. Round trips between two accounts

Honest trade rarely sends the same money back and forth. Two accounts that keep paying
each other are likely "washing" money to create fake activity. This finds pairs of
accounts that send money in both directions and totals the round-trip volume. Runs in
about three seconds.

```cypher
MATCH (a:Account)-[f:TRANSFERRED_TO]->(b:Account)-[g:TRANSFERRED_TO]->(a)
WHERE a.account_id < b.account_id
RETURN a.account_id AS a_id, b.account_id AS b_id,
       round(sum(f.amount + g.amount), 2) AS round_trip_volume,
       count(*) AS leg_count
ORDER BY round_trip_volume DESC
```

Read it as: each row is a pair of accounts bouncing money between themselves. High
volume with many legs is the strongest wash signal. The columns:

* `a_id` and `b_id`: the two accounts in the pair.
* `round_trip_volume`: all the money sent between them, both directions added together,
  in dollars.
* `leg_count`: how many transfers passed between them in total, counting both
  directions. A 4 means four transfers bounced back and forth.

#### 4. Accounts that move more than they hold

An account holding $1,000 that pushes $100,000 through is acting like a pipe, not a
wallet. This compares each account's total outflow to its current balance. Runs in
about three to four seconds.

```cypher
MATCH (a:Account)-[t:TRANSFERRED_TO]->(:Account)
WHERE a.balance > 0
WITH a.account_id AS account_id, a.balance AS balance, sum(t.amount) AS outflow
RETURN account_id, round(balance, 2) AS balance, round(outflow, 2) AS outflow_volume,
       round(outflow / balance, 1) AS velocity_ratio
ORDER BY velocity_ratio DESC
```

Read it as: a high `velocity_ratio` means the account moved far more money than it
ever held. Treat it as one weak signal, since a pass-through account ends near empty by
design, so combine it with the others rather than trusting it alone. Each row is one
account:

* `account_id`: the account.
* `balance`: how much money it holds right now, in dollars.
* `outflow_volume`: the total it has sent out, in dollars.
* `velocity_ratio`: the outflow divided by the balance. A 287 means it moved about 287
  times its current balance.

### Stage 3: Integration (collecting the money and pulling it out)

#### 5. Collection accounts: money piling in from many senders

A normal person is not paid by dozens of strangers in a single week. An account that
receives money from many different senders in a short window is a classic collection
point. This query returns one row per sender-and-receiver pair in the last week of the
data. Runs in about three to four seconds.

```cypher
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WHERE t.transfer_timestamp >= datetime("2024-03-23T23:58:00Z")
WITH dst.account_id AS recipient, src.account_id AS sender,
     count(t) AS legs, sum(t.amount) AS pair_amount
RETURN recipient, sender, legs, pair_amount
```

Each row is one sender paying one recipient:

* `recipient`: the account receiving the money, the one you are investigating.
* `sender`: one account that paid into it.
* `legs`: how many separate transfers that one sender sent to that recipient.
* `pair_amount`: the dollars that one sender sent to that recipient, added up.

Then count how many rows each `recipient` has: that count is the number of different
senders paying into it. Five or more different senders in a week is a collection
account worth investigating.

#### 6. Spray accounts: one account paying out to many

The mirror image. One account splitting a big pile into many small transfers to many
different accounts is "smurfing." This query returns one row per sender-and-recipient
pair in the last week of the data. Runs in about three to four seconds.

```cypher
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WHERE t.transfer_timestamp >= datetime("2024-03-23T23:58:00Z")
WITH src.account_id AS sender, dst.account_id AS recipient,
     count(t) AS pair_transfers, sum(t.amount) AS pair_outflow
RETURN sender, recipient, pair_transfers, pair_outflow
```

Each row is one sender paying one recipient:

* `sender`: the account paying out, the one you are investigating.
* `recipient`: one account it paid.
* `pair_transfers`: how many separate transfers went from the sender to that recipient.
* `pair_outflow`: the dollars sent to that recipient, added up.

Then count how many rows each `sender` has: that count is the number of different
accounts it paid. Five or more different recipients in a week is a spray account.

These same two result sets also tell you who the **hubs** are. Count senders per
recipient and recipients per sender across all the rows, and the accounts with the
biggest combined counts sit at the center of the network. Those are the ringleaders or
the central collection points.

#### 7. Courier accounts: lots of transfers, almost no shopping

A real customer both moves money to people and buys from shops. An account with heavy
peer-to-peer transfer activity but almost no merchant spend behaves like a courier, not
a customer. This takes two quick queries. The first counts each account's transfers
(both directions). The second counts each account's merchant purchases. Each runs in
about three seconds.

```cypher
MATCH (a:Account)-[tr:TRANSFERRED_TO]-(:Account)
WITH a.account_id AS account_id, count(tr) AS transfer_count
RETURN account_id, transfer_count
ORDER BY transfer_count DESC
```

```cypher
MATCH (a:Account)-[tw:TRANSACTED_WITH]->(:Merchant)
WITH a.account_id AS acct, count(tw) AS merchant_count
RETURN acct AS account_id, merchant_count
ORDER BY merchant_count DESC
```

Each row in the first result is one account:

* `account_id`: the account.
* `transfer_count`: how many transfers it took part in, sending or receiving, added
  together. This is its total peer-to-peer activity.

Each row in the second result is one account:

* `account_id`: the account.
* `merchant_count`: how many purchases it made from merchants. An account missing from
  this list made zero merchant purchases.

Then line the two results up by account. An account with many transfers (say 100 or
more) but very few merchant purchases (under 20, which includes zero) is acting like a
money courier. Accounts that never appear in the second list have no merchant spend at
all, which is the strongest version of the signal.

## Visualize the suspects

The queries above give you lists. The payoff of a graph is seeing the *shape*. Take any
account id a query flagged, paste it into one of the queries below, and run it in the
Aura Workspace Query tab to draw the picture. These return node and relationship
variables, so the Workspace renders them as a graph rather than a table.

One rule makes or breaks this: **always anchor on a specific account id.** Filtering on
one id (`{account_id: 184}`) pushes a selective filter down to the warehouse, so the
query stays fast and returns few enough nodes to draw. The same pattern without an
anchor scans the whole table and returns far too much to render. The example ids below
are real accounts from the test data; swap in your own.

#### See a collection account (the fan-in star)

Anchor on a recipient flagged by demo query 5. This draws every account that paid into
it, fanned out around the center. Account 184 below receives from two dozen different
senders. Returns up to 50 incoming transfers in about 9 seconds.

```cypher
MATCH (sender:Account)-[t:TRANSFERRED_TO]->(a:Account {account_id: 184})
RETURN sender, t, a
LIMIT 50
```

To pick your own collection account, this finder returns the recipients with the most
different senders in the last week, in about a second. Use the top `recipient` as the
anchor above.

```cypher
MATCH (src:Account)-[t:TRANSFERRED_TO]->(dst:Account)
WHERE t.transfer_timestamp >= datetime("2024-03-23T23:58:00Z")
WITH dst.account_id AS recipient, src.account_id AS sender, count(t) AS legs
WITH recipient, count(*) AS senders
RETURN recipient, senders
ORDER BY senders DESC
LIMIT 5
```

#### See a spray account (the fan-out star)

Anchor on a sender flagged by demo query 6. This draws everyone it paid, fanned out
around the center: the mirror image of the collection star. Returns up to 50 outgoing
transfers in about 10 seconds.

```cypher
MATCH (a:Account {account_id: 16570})-[t:TRANSFERRED_TO]->(recipient:Account)
RETURN a, t, recipient
LIMIT 50
```

To pick your own, swap `src`/`dst` in the finder above to rank by distinct recipients
per sender.

#### See a round-trip pair (the wash edge)

Anchor on the two ids from demo query 3. This draws the two accounts with the transfers
running between them in both directions, which is the wash shape in its simplest form.
Returns a handful of edges in under three seconds.

```cypher
MATCH (a:Account {account_id: 13044})-[t:TRANSFERRED_TO]-(b:Account {account_id: 17621})
RETURN a, t, b
```

For more warm-up and visualization queries (ego networks around merchants, two accounts
linked through a shared merchant, transfer chains), see
[`basic-graph-examples.md`](basic-graph-examples.md). The same anchoring
rule applies to all of them.

## How it all ties together

The three stages form a funnel that turns 25,000 accounts into a short list of suspects
and then into a connected ring.

1. **Placement (queries 1 and 2)** is the wide net. Simple counts and thresholds flag
   accounts that got money into the system the wrong way: structuring just under the
   limit, and brand-new accounts already moving large sums.
2. **Layering (queries 3 and 4)** follows the money for those suspects. Round trips and
   high move-to-balance ratios confirm the money is being churned to hide its origin,
   not just sitting in odd-looking accounts.
3. **Integration (queries 5, 6 and 7)** connects the suspects to each other. Collection
   accounts show where the money regathers, spray accounts and hubs show who is
   distributing it, and courier accounts show who is moving it without behaving like a
   real customer.

The same data answers all three stages. You start broad, you confirm the behavior, then
you connect the accounts into a group. A single suspicious number is easy to explain
away. The same account showing up in placement, then layering, then at the center of
the integration step is the story that holds up.

One honest limitation worth saying out loud in the demo: these queries surface
candidates, not proven fraud. The power is in the funnel. An account that lights up at
every stage is far more interesting than one that trips a single rule.

## Candidates, not verdicts

Three caveats keep the demo honest:

- **Validate against ground truth.** The dataset includes a held-out
  `account_labels.is_fraud` table. Measure the precision and recall of any rule against
  it before trusting it. Confident language such as "clearly fraud" is not earned until
  you have.
- **Legitimate accounts share the fingerprint.** Payment aggregators, payroll
  processors, marketplace settlement accounts, and P2P-app float accounts show the same
  high fan-in, rapid turnover, and low own-merchant activity. The hard part is separating
  these from fraud, not finding high-throughput accounts.
- **Watch confounded metrics.** The velocity ratio in query 4 divides by current
  balance, which the behavior itself drives toward zero. Combine signals rather than
  ranking on any single confounded one.
