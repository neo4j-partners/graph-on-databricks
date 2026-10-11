# NAMS 424 external_database_error on GET /v1/conversations

Source examined: `/Users/ryanknight/projects/neo4j-labs/project-nams`, refs `origin/main` and `origin/development` after `git fetch`. Nothing in that repo was changed. No network call was made except the fetch. Every `path:line` below refers to `origin/main` unless the text names another ref.

## Summary

The 424 comes from the NAMS service failing to run a query against the Neo4j database behind your workspace, and the code only produces this status when that workspace is in "external" mode. No commit on `main` or `development` removes or reduces these 424s. The code gives a plausible mechanism, a dropped or stalled connection between NAMS and that database, but the code alone cannot confirm it. A service log line for the failing request would settle it.

- **Symptom:** `GET /v1/conversations` intermittently answers `424` with `external_database_error`, then answers `200` on the next call.
- **Best-supported cause:** One query from NAMS to the workspace database failed at the network or gateway level, and NAMS labels every such failure on an external database as a 424. The code shows no retry before it answers.
- **Condition for a 424:** The workspace must have `dbMode = "external"`. A managed workspace that suffers the same failure answers `503 db_unreachable`, never `424` (`packages/gaylord-db/external_fault.go:32`).
- **Fix on a branch:** Neither branch has one. `main` changed the status code from 502 to 424 and changed how the background worker flags broken workspaces. `development` added a retry for a database that is still starting, and that retry runs only during provisioning.
- **Released or deployed:** The 424 change is released in tag `v1.2.0` (2026-10-08) on `main`. Your client sees 424, and the old code answered 502, so the hosted service runs at least that change. The two `development` commits are unreleased, and nothing shows them deployed to the hosted service.
- **What the client should do:** Retry the connect probe with a short backoff and treat a repeated 424 as a real outage. Waiting after a reset is reasonable, but the code does not require it.
- **What stays unknown:** Whether your workspace is in external mode, what the underlying error text was, what the console "reset" does, and which environment serves `memory.neo4jlabs.com`.

## Investigation

### Terms used below

- **Workspace:** A tenant in NAMS. Each workspace has its own Neo4j database for conversations and memory.
- **Managed database:** A Neo4j instance that NAMS creates for the workspace through its sandbox service. Workspace field `dbMode` is `managed`.
- **External database:** A Neo4j instance the workspace owner supplies. Workspace field `dbMode` is `external`. NAMS stores its URI and encrypted password on the workspace record (`packages/gaylord-db/client.go:611-646`). The code comment at `services/nams-memory-worker/internal/sandbox_reconciler_external.go:81` shows that a workspace can also run in external mode while pointing at a database on the NAMS-managed host.
- **Query API:** The HTTP endpoint on a Neo4j database (`/db/<name>/query/v2`) that NAMS uses to send Cypher (`packages/gaylord-db/queryapi.go:318-320`).
- **Worker and reconciler:** `nams-memory-worker` is a background service. Its reconciler wakes on a timer, probes each external workspace with `RETURN 1`, and writes a `status` onto the workspace record (`services/nams-memory-worker/internal/sandbox_reconciler.go:148-158`).
- **Unrecoverable flip:** The reconciler sets `status = "error"` and stops re-probing, because only the owner can fix the connection.

### How the request reaches the error

To trace the path, follow one `GET /v1/conversations` call through the code.

1. `ListConversations` handles the route (`services/nams-api/internal/handlers/short_term.go:133`).
2. To get a database handle, it calls `getTenantDB` (`short_term.go:167`, defined at `services/nams-api/internal/handlers/handlers.go:120`). That calls `Client.TenantDB` (`packages/gaylord-db/client.go:503`), which reads the workspace record from the NAMS control database.
3. If `dbMode` is `external`, `resolveExternalTenantDB` builds a handle that carries a special HTTP client (`client.go:611-646`). Having that client is what makes a handle "external" (`packages/gaylord-db/tenant.go:50-52`). The request path never reads the workspace `status` field. A workspace flagged `error` by the worker still gets live queries.
4. The handler runs the conversation query (`short_term.go:173`). `TenantDB.Query` calls `run` once (`tenant.go:125, 144-147`). There is no loop and no retry on `main`.
5. `postQuery` sends the HTTP request (`packages/gaylord-db/queryapi.go:324-361`). A transport error becomes `query api request on <host>: ...`. A non-2xx answer that is not a Neo4j error becomes `query api HTTP <status>: ...` (`queryapi.go:382`). A 404 becomes `ErrTenantSandboxGone` (`queryapi.go:371-373`).
6. Any failure passes through `settle`, which tags it as an external fault when the handle is external (`tenant.go:151-154`, `packages/gaylord-db/external_fault.go:31-36`).
7. `respondTenantQueryError` asks `classifyTenantFault` for the response (`short_term.go:175`, `services/nams-api/internal/handlers/errors.go:103-110`).

The classification has these branches, in order (`errors.go:48-67`):

| Order | Condition | Response | Line |
| --- | --- | --- | --- |
| 1 | The caller disconnected | 499 `client_disconnected` | 51 |
| 2 | The error wraps `ErrTenantSandboxGone` (DNS "no such host" or HTTP 404) | 409 `database_unavailable` | 54 |
| 3 | The error carries the external-fault tag | **424 `external_database_error`** | 57-59 |
| 4 | A Neo4j error that is not tagged | 500 `cypher_error` | 60-61 |
| 5 | Timeout or network error on a managed database | 503 `db_unreachable` | 62-64 |
| 6 | Anything else | 500 `internal` | 66 |

The tag is applied to every database-side failure of an external database. The rules are at `external_fault.go:38-65`:

- The tag is skipped when the caller cancelled, when NAMS never sent the request, when the result was too large, or when Neo4j returned a `Statement`, `Schema`, `Request`, or `Procedure` client error. Those describe the statement NAMS sent.
- The tag is applied to everything else: connection failures, timeouts, HTTP answers from a proxy or load balancer, `Security.*` errors, `Database.*` errors, `TransientError.*` errors, and `DatabaseError.*` errors. This includes a rate-limit lockout, which is keyed on the source IP rather than on the workspace credential (`queryapi.go:150-153`).

The timeouts that can produce a tagged failure on an external handle:

- Dial timeout of 5 seconds (`packages/gaylord-db/uri_validation.go:231`).
- TLS handshake timeout of 10 seconds (`uri_validation.go:265`).
- Response header timeout of 10 seconds (`uri_validation.go:266`).
- Whole-request timeout of 120 seconds (`client.go:248`).
- Idle keepalive connections are dropped after 15 seconds by default (`client.go:1489`, `AGENTS.md:79`).

The 424 body carries only the code, a generic message, and the workspace ID (`errors.go:58-59, 105-109`). The real cause appears only in the service log. NAMS logs the failure at WARN with the error text, workspace ID, and code (`errors.go:91`). It also logs `query api request failed` at `queryapi.go:351` and `query api error response` at `queryapi.go:381` or `queryapi.go:396`.

### What "external database" means and when it is reported

The service reports `external_database_error` for any failure of the owner's database that NAMS did not cause. The commit message for `ce8bb68d` and the comment at `errors.go:41-45` give the reason: only the owner can fix such a failure, and the load balancer should not count it as a NAMS 5xx. The code does not separate the causes. A failed connection, a timeout, a reset, a proxy answering 502 or 403, a credential lockout, and a database that is stopped all produce the same 424.

These cases are not 424:

- A 404 from the database or a DNS "no such host" is `409` (`errors.go:54`). For a database that is only starting, `handleSandboxGone` first asks the sandbox service whether the database exists (`tenant.go:156-170`).
- A workspace still provisioning answers `503 workspace_not_provisioned` (`handlers.go:155-188`).
- A workspace with a failed credential lookup answers `500 database unavailable` (`handlers.go:190-191`).
- Pool exhaustion has no dedicated code path. The shared client allows 20 idle connections per host (`uri_validation.go:264`) and does not cap total connections, so a wait for a free slot would not appear as a pool error.

A paused or cold Aura instance. The worker comment at `sandbox_reconciler_external.go:74` says "a paused Aura instance resets TLS". The worker therefore treats that as an ordinary counted failure. A paused instance fails every request until someone resumes it. Your `curl` returned 200 six times, and a paused database would have failed those too. Pause alone does not fit the intermittent pattern.

### Does the code mark a workspace unrecoverable?

The unrecoverable flip is a separate mechanism from the 424. It changes the workspace `status` on the control database. It does not change what `GET /v1/conversations` answers.

- **Scope of the flip:** `markExternalUnrecoverable` applies only when the probe error is a DNS "no such host" or a TLS configuration fault, meaning a certificate for another name or from an untrusted issuer (`sandbox_reconciler_external.go:254-264`, `external_fault.go:69-89`). Any other probe error returns `false` at line 262 and takes the ordinary path.
- **One failure does not flip it:** The ordinary path counts consecutive failed ticks and acts at `externalUnreachableThreshold = 3` (`sandbox_reconciler_external.go:14, 186-216`). The reconciler default interval is one hour (`sandbox_reconciler.go:187`), and the deployed interval is not visible in the code. The one exception is the recovery re-probe of a workspace already in `error`, which can flip it at once (`sandbox_reconciler_external.go:140`).
- **A later success clears the count, up to a point:** A successful probe resets the counter (`sandbox_reconciler_external.go:61-65`). A workspace flipped by the ordinary counter reactivates itself when its database answers again (`sandbox_reconciler_external.go:120-169`). A workspace flipped as unrecoverable is never re-probed, and only a reconnect through `PUT /v1/workspace/database` reactivates it (`sandbox_reconciler_external.go:246-253`, `services/nams-tenants/internal/handlers/database.go:571-585`).
- **What commit `9f130ee0` changes:** The threshold flip used to check only `status = "active"` and `dbMode = "external"`. A reconnect saved between the failing probe and the flip still matched and retired a connection nobody had probed. The flip now also requires `dbUnreachableCount` to equal the value that tick's increment returned. A reconnect removes that property, so the flip no longer matches (`sandbox_reconciler_external.go:240-244`). The change is on `main` (dated 2026-10-07, shipped in `v1.2.0`) and on `development`, because `development` contains the same commit.

This mechanism cannot explain an intermittent 424 on one request. The request path does not read `status`, and the flip needs three consecutive hourly failures of a specific kind.

### What main contains

The commits below are the ones on `main` that touch this problem. All are in tag `v1.2.0`, which points at `dc218a21` (2026-10-08 07:12 UTC).

| Commit | Date | Effect |
| --- | --- | --- |
| `f0ff2ab7` | 2026-09-30 | Introduces the external-fault tag. |
| `11d24bf5` | 2026-09-30 | The reconciler counts every external probe failure and reactivates flipped workspaces on its own. |
| `969e582e` | 2026-09-30 | Logs tenant failures that NAMS cannot fix at WARN instead of ERROR. |
| `ce8bb68d` | 2026-10-07 | Answers `424` instead of `502` for an external fault, and makes every call site answer the status it classified rather than a hardcoded `500`. |
| `e3ec8325` | 2026-10-07 | The worker stops re-probing an external workspace whose host does not resolve or whose TLS name is wrong. |
| `9f130ee0` | 2026-10-07 | A reconnect wins over the unrecoverable flip. |
| `20961146` | 2026-10-07 | Documents 409, 424, and 503 on each route in the OpenAPI annotations, including `short_term.go:128`. |

None of these makes a query succeed that would have failed before. `ce8bb68d` changes only the number on a failure that already happened. Its message says that the earlier code answered 502 for this error class, so a client that sees 424 is talking to a service that includes this commit.

Retry and backoff:

- No retry exists on the query path (`tenant.go:144-147`).
- No `Retry-After` header is set on a 424 (`errors.go:103-110`). The code sets `Retry-After` for `503 user_partition_not_ready` only, as documented at `docs/api-reference.adoc:71`.
- `docs/api-reference.adoc` does not list 424. It lists 503 as "Retry later" (`api-reference.adoc:126-127`).
- The OpenAPI annotation tells the caller that "only its owner can fix it: check that it is running and that the connection on the Database page is correct" (`short_term.go:128`). The documentation therefore presents 424 as a persistent owner problem. It does not call it transient.
- `CHANGELOG.md:23` describes the change as a way to tell service issues from workspace-specific problems.
- NAMS has retries elsewhere, for example three tries with backoff when the worker fetches a message (`docs/architecture.adoc:121`). They are unrelated to this path.

Evidence that transport resets happen on the NAMS side. The code records that Aura's load balancer drops idle keepalive connections without a close signal. A reused connection then fails with "connection reset by peer", and the comment at `client.go:1480-1489` counts 9,147 of them in one production week against four hosts. That comment concerns the shared client, and the external client reads the same idle-timeout setting (`uri_validation.go:269`). For an external workspace, each such reset becomes a 424. Go's standard HTTP transport does not resend a POST after a reset on a reused connection. NAMS sends its queries as POST (`queryapi.go:336`), so the failure reaches the handler. I did not test this behaviour, so treat it as reasoning from the standard library rather than as verified.

### What development contains

`development` is `main` plus four commits. `git log origin/main..origin/development` lists:

| Commit | Date | Effect |
| --- | --- | --- |
| `049f35cf` | 2026-10-09 | `EnsureManagedTenantSchema` resends a schema statement that a starting database answers with 404, for up to two minutes. Source: `packages/gaylord-db/tenant.go:162-175` and `client.go:1353-1364` on `origin/development`. |
| `bdb7a516` | 2026-10-09 | Returns the cancellation, instead of the 404 being resent, when the context ends during the resend delay. |
| `2f4cd9e7` | 2026-10-08 | Duplicate of the `v1.2.0` release commit that carries the same release. |
| `165220c7` | 2026-10-09 | Adds a Neo4j Labs disclaimer file and a README line. |

The retry in `049f35cf` is reached only through `awaitingStartup`, and `EnsureManagedTenantSchema` is its only caller (`client.go:1359` on `origin/development`). It applies to managed databases during provisioning. A request to `GET /v1/conversations` never takes this path, and a 404 on that request returns 409, not 424. The commit message reports that a freshly started database answers intermittent 404s for several seconds after the readiness probe passes. That finding shows that a starting database behaves unevenly, but the retry does not extend to external workspaces or to the request path.

`git diff origin/main origin/development --name-status` shows five changed files: `LABS_DISCLAIMER.txt`, `README.md`, `packages/gaylord-db/client.go`, `packages/gaylord-db/schema_verify_test.go`, and `packages/gaylord-db/tenant.go`. Nothing else differs.

### How main and development differ on this problem

- **Request path:** Identical. `errors.go`, `external_fault.go`, `queryapi.go`, `uri_validation.go`, and the reconciler files are the same on both branches.
- **Reconnect-wins fix `9f130ee0`:** Present on both.
- **Startup retry:** Only on `development`, and only during provisioning of a managed database.
- **Release state:** `v1.2.0` sits on `main` at `dc218a21`. `development` carries `2f4cd9e7`, its copy of that release commit. The two commits dated 2026-10-09 come after the tag, and `CHANGELOG.md` on `development` has no entry for them.
- **Deployment:** `.github/workflows/deploy-ecs.yml:8` runs the workflow on pushes to `main` and `development`. Line 427 selects the `production` environment for `main` and the `development` environment for any other branch. The repo documents `https://memory.neo4jlabs.com` as the public host (`docs/api-reference.adoc:13`) but does not say which environment serves it. I infer that production serves it and runs `main`. That inference rests on the workflow, and a deployed task definition or a `/health` version string would confirm it.

### Could the console reset cause the 424s?

I could not find a "reset database" action on `main` or `development`. A search for reset, wipe, clear, and purge routes in the services found none. The actions that resemble a reset are these:

- **Reprovision** (`POST /v1/workspace/reprovision`, `services/nams-tenants/internal/handlers/handlers.go:774-792`). It moves the workspace to `provisioning`. While in that state, the API answers `503 workspace_not_provisioned` (`handlers.go:155-188`), which is not 424.
- **Switch database mode** (`PUT /v1/workspace/database`, `database.go:497-641`). Switching to external tests the connection, applies the schema, and sets `status = "active"`. A failed test answers `424` with a different body, `external database connection failed`, from the tenants service (`database.go:536`, which uses `http.StatusFailedDependency`). That response does not come from `GET /v1/conversations`.
- **Database copy with `wipeDestination`** (`services/nams-memory-worker/internal/dbcopy/dbcopy.go:385-386`, `docs` annotation at `services/nams-api/internal/handlers/workspace_docs.go:477`). The comment at `dbcopy.go:233` says wipe-then-copy is not atomic.

Reasoning on whether a reset explains the 424s:

- An empty database returns an empty list with `200`. Emptying data alone does not produce a 424.
- Your Run 1 produced 8 failures out of 24 turns. If Run 1 ran before the reset, the reset is not required for the symptom.
- A workspace whose database is restarting after a reset could fail requests at the network level. For an external workspace that would become a 424. The code cannot show this, because it contains no reset action and no record of what the console did to the backing database.
- After a switch or reprovision, other NAMS services cache managed credentials for up to 60 seconds (`client.go:224-231`). Stale credentials aimed at a removed managed database give 404 or DNS failure, which is `409`, not `424`.

### What the evidence cannot show

- **Mode of your workspace:** The code makes 424 reachable only for external mode. The Database page in the NAMS console shows the mode. If it says managed, the 424 contradicts the code on `main`, and the deployed build must differ from what I read.
- **The underlying error:** The 424 body hides it. The service log at WARN for `list conversations: query failed` carries the error text. Search the log for your workspace ID near the failure time. A message such as `connection reset by peer`, `context deadline exceeded`, `query api HTTP 502`, or `AuthenticationRateLimit` would identify the cause.
- **Why concurrency did not matter:** Failures occurred at concurrency 6 and 3. Per-request transport failures would not depend on concurrency. A longer gap between requests would raise the chance that a pooled connection went idle past the 15-second limit and got reset. This idle-connection explanation fits the data, and I could not test it. A run with requests spaced under 15 seconds apart, compared with a run spaced over 30 seconds, would test it.
- **The count mismatch:** The runs lost 8 and 11 turns, and NAMS held 16 and 20 conversations. The code cannot reconcile those numbers. Other routes the SDK calls can also answer 424, and the client's own retries and the SDK's call sequence are outside this repo.
- **Deployed build:** The workflow suggests `main` deploys to production. A running task image tag or a deploy record would confirm the exact commit.
- **Reconciler interval:** The default is one hour. The deployed value is unknown.
- **Reset behavior:** No code describes the console reset. A description from the console or from the team that owns it would settle that part.

### What the client should do

1. Retry the connect probe on 424. `GET /v1/conversations` is a read, so a retry is safe. Use three attempts with waits of about 0.5, 1, and 2 seconds, plus jitter. The failures you saw cleared on the next call.
2. After the retries fail, treat the 424 as a real outage and skip memory for that turn, as the client does now. Persistent 424s match the documented meaning, which is that the owner must check the database and the connection.
3. Reuse one `MemoryClient` across turns where possible. That removes one probe per turn and one chance per turn to hit the failure.
4. After a console reset, poll `GET /v1/conversations` until it answers `200` twice in a row before starting traffic. The code does not require this wait, but it costs little and guards against a database that is still starting.

### What the NAMS team should do

1. Read the WARN log lines for the failing requests and report the error text. That identifies the cause and tells the team whether the 424s are transient resets or something persistent.
2. Retry once inside `TenantDB.run` for read statements that fail on a reused connection with a reset or EOF. Today no code path retries (`tenant.go:144-147`).
3. Lower `NAMS_IDLE_CONN_TIMEOUT_SECS` below its 15-second default if the logs show resets on reused connections. The code comment at `client.go:1480-1489` says the correct value is unknown and should be tuned against the reset rate.
4. Split the 424 into causes. Add a `detail` or a distinct code for a transient transport failure, and send `Retry-After` for it. The generic message today tells callers the failure is permanent and owner-fixable, and the evidence shows it can be transient.
5. Add 424 to `docs/api-reference.adoc`. The hand-written error table omits it (`api-reference.adoc:97, 126-127`), and only the generated OpenAPI annotations mention it.
6. Document what the console reset does to the backing database, and whether the API answers a defined status while the database restarts.
