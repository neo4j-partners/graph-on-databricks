# Generate traffic

The traffic project fills NAMS with conversations. Fake analysts call the deployed app, and the app writes to NAMS. You can run it from your laptop or as a Databricks Job.

How the generator behaves:

- **Analysts:** The generator uses 12 fixed analyst names. In the first session, each analyst states a name, a team, a manager, a focus, and an owned case. Later sessions do not repeat it. They open with a first name, an "N. Surname" form, or a team alias. An answer that uses the focus or the case shows recall working.
- **Questions:** The questions mix generic graph questions with instance questions. Instance questions use real graph ids, such as accounts, communities, merchants, and phone numbers.
- **Same prompts every run:** The prompt text does not depend on the run id. Only the user, session, and invocation ids carry it. A run before and a run after an ontology change ask identical questions.
- **Shared community:** Cases go to analysts in turn. Users 1 and 6 investigate the same community from different teams, so use `--users 6` or more to get that overlap.
- **Graph ids:** The ids in `traffic/nams_traffic/scenarios.py` come from the seeded graph. Refresh them if the graph is seeded again.
- **Through the app:** Traffic goes through the app, so only the app holds the NAMS key.
- **Safe retries:** Each turn has a fixed invocation id. A retry cannot save a turn twice.
- **Replay:** Running the same `--run-id` again replays the stored invocations. It writes no new conversations.

Both run modes need a deployed app with the NAMS key attached, plus `DATABRICKS_CONFIG_PROFILE` and `APP_URL` in your shell. Skip this block if both variables are already set.

```bash
export DATABRICKS_CONFIG_PROFILE=<your-profile>
export APP_URL=$(databricks apps get agent-bricks-neo4j-graph-agent \
  -p "$DATABRICKS_CONFIG_PROFILE" -o json | jq -r .url)
```

## Run it from your laptop

```bash
cd traffic
uv sync
uv run agent-traffic --dry-run --users 6 --sessions-per-user 2 --turns-per-session 2
uv run agent-traffic --profile "$DATABRICKS_CONFIG_PROFILE" --app-url "$APP_URL" \
  --users 6 --sessions-per-user 2 --turns-per-session 2
```

Or run `make traffic` from `neo4j-mcp-graph-agent/`. It runs the same live run without the dry run. It looks up `APP_URL` when the variable is unset. Change the size with `USERS=`, `SESSIONS=`, and `TURNS=`.

The dry run prints the plan and calls nothing. The second command signs in with your profile. This run is 24 turns. The setting `--users 6` is the smallest run that shows one community shared by two analysts.

The run calls the app as you. Your user must be trusted before the deploy, as step 7 of [Quick start cloud with make](../README.md#quick-start-cloud-with-make) explains.

**Check NAMS:** Open your NAMS workspace and look for users named `nams-load-<run-id>-user-NNNN`. Then check the app logs. Open the app's Logs tab, or run `agentbricks deployments logs agent-bricks-neo4j-graph-agent`. The shortcut is `make logs`. Each line that starts with `memory identity bound:` should show `user=nams-load-...` and a `trusted caller` source. If it shows `user=<your email>` instead, your email is missing from `MEMORY_TRUSTED_CALLERS`. Fix it as step 7 of [Quick start cloud with make](../README.md#quick-start-cloud-with-make) explains, then deploy again.

| Option | What it sets | Default |
| --- | --- | --- |
| `--users` | The number of analysts | 20 |
| `--sessions-per-user` | The sessions each analyst starts | 3 |
| `--turns-per-session` | The questions in each session | 4 |
| `--concurrency` | The sessions that run at once | 4 |
| `--timeout` | The seconds allowed for one turn | 300 |
| `--retry-attempts` | The tries for each turn | 1 |
| `--continue-after-error` | Keeps going after a failed turn | Off, so the run stops |
| `--run-id` | The name that the users and sessions carry | A random id |
| `--verify-nams` / `--no-verify-nams` | Turns the stored-count check on or off | On when a key is found, off when it is not |

The default run is 240 turns. Each turn takes 20 to 60 seconds, so the full run takes close to an hour.

### The stored-count check

The app answers a turn even when NAMS is down, so a completed turn does not prove that NAMS stored it. The run therefore checks NAMS itself.

- **Readiness wait:** Before it sends any turn, the run waits until NAMS answers 200 twice in a row. A database that was just reset can fail at first.
- **Stored count:** After the last turn, the run counts the conversations that NAMS holds for each session of the run. It prints a `NOT STORED` line for every session that holds fewer turns than completed. It prints a `FAILED` line for every turn that failed.
- **Exit codes:** The run exits with 0 when every turn completed and NAMS stored all of them. It exits with 1 when a turn failed or was skipped. It exits with 2 when NAMS stored too few turns or was not ready.
- **The key:** The check needs `MEMORY_API_KEY` in your shell or in `.env`. The make target runs from `traffic/`, so the check also reads `../.env`. Without a key, the check is skipped with a warning. If you pass `--verify-nams` and no key exists, the run exits with 1 before it sends any turn.
- **Turning it off:** Pass `--no-verify-nams` to skip both the readiness wait and the check.
- **Databricks Job:** The Job has no `MEMORY_API_KEY`, because only the app holds the key. The Job skips the check and prints a warning.

If the check exits with 2, reset NAMS and run the traffic again.

## Run it as a Databricks Job

The Databricks Apps proxy returns a 401 for the token that a job gets from its own runtime. So the job signs in as a service principal. This setup happens once.

1. **Create the principal and its secret:** The first command saves the principal's id in `SP_ID` and its application id in `SP_CLIENT_ID`. The last command prints the OAuth secret once, so copy it now.

   ```bash
   SP_JSON=$(databricks service-principals create --display-name nams-traffic-runner \
     -p "$DATABRICKS_CONFIG_PROFILE" -o json)
   export SP_ID=$(jq -r .id <<<"$SP_JSON")
   export SP_CLIENT_ID=$(jq -r .applicationId <<<"$SP_JSON")
   databricks service-principal-secrets-proxy create "$SP_ID" -p "$DATABRICKS_CONFIG_PROFILE"
   ```

2. **Store the credentials:** The `client-id` command reads `SP_CLIENT_ID`. The `client-secret` command asks for the OAuth secret.

   ```bash
   databricks secrets create-scope nams-traffic -p "$DATABRICKS_CONFIG_PROFILE"
   databricks secrets put-secret nams-traffic client-id --string-value "$SP_CLIENT_ID" \
     -p "$DATABRICKS_CONFIG_PROFILE"
   databricks secrets put-secret nams-traffic client-secret -p "$DATABRICKS_CONFIG_PROFILE"
   ```

3. **Let the principal call the app:**

   ```bash
   databricks apps update-permissions agent-bricks-neo4j-graph-agent -p "$DATABRICKS_CONFIG_PROFILE" \
     --json '{"access_control_list":[{"service_principal_name":"'"$SP_CLIENT_ID"'","permission_level":"CAN_USE"}]}'
   ```

4. **Trust the principal's user ids:** The app honors the `user_id` in a request only from callers listed in `MEMORY_TRUSTED_CALLERS`. Add the principal's application id to that entry in `app.yaml`, then run `agentbricks deploy neo4j-graph-agent` again. Or run `make deploy`. The checked-in entry holds the `nams-traffic-runner` application id and a user from this repo's workspace. If you created a new principal, replace the id with `$SP_CLIENT_ID`. Separate the values with commas. Keep your own user email there for laptop runs, as step 7 of [Quick start cloud with make](../README.md#quick-start-cloud-with-make) explains. If the principal is missing, the app ignores the synthetic users and saves every traffic turn under the principal itself.

   ```yaml
   - name: MEMORY_TRUSTED_CALLERS
     value: <SP_CLIENT_ID>,<your-email>
   ```

5. **Deploy the bundle and run the job:** The job runs as you, so you need `READ` on the scope `nams-traffic`.

   ```bash
   cd traffic
   databricks bundle deploy -p "$DATABRICKS_CONFIG_PROFILE" --var app_url="$APP_URL"
   databricks bundle run nams_traffic -p "$DATABRICKS_CONFIG_PROFILE" --var app_url="$APP_URL" \
     --params users=6,sessions_per_user=2,turns_per_session=2
   ```

The job parameters:

| Parameter | What it sets | Default |
| --- | --- | --- |
| `app_url` | The URL of the deployed app. Pass it with `--var`. | None, so it is required |
| `credentials_scope` | The scope that holds the principal's credentials | `nams-traffic` |
| `users`, `sessions_per_user`, `turns_per_session`, `concurrency`, `timeout` | The same settings as the CLI options. Change them with `--params`. | The CLI defaults |

To run the job every hour, set `pause_status: UNPAUSED` in `traffic/databricks.yml` and deploy the bundle again. The schedule is paused by default.

To check a run:

- **Job output:** Open the run URL that `bundle run` prints. The log ends with `done ok=N failed=0`.
- **NAMS:** Open your NAMS workspace and look for users named `nams-load-<run-id>-user-NNNN`. The run id is in the first log line.
- **Bound identity:** After deploy, check the logs for the bound principal of a traffic turn. Open the app's Logs tab and find a line that starts with `memory identity bound:`. A traffic turn should show `user=nams-load-...` and a `trusted caller` source that names the header and the principal. If it shows `user=<the principal>` instead, the principal is missing from `MEMORY_TRUSTED_CALLERS`, or the proxy sends it in a different header.

If something fails:

- **401 from the app:** The principal lacks `CAN_USE` on the app, or the credentials in the scope are wrong.
- **`no value assigned to required variable app_url`:** Add `--var app_url=...` to the command.
- **No data in NAMS:** Check that the `nams-api-key` resource is still attached to the app.
- **All turns under one user in NAMS:** The principal is not in `MEMORY_TRUSTED_CALLERS`. See step 4.

The app is not part of this bundle. `agentbricks deploy` provisions its runtime store, session store, and MCP grants, and a bundle app resource would conflict with that.
