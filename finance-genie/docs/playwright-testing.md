# Playwright UI Testing Guide

A practical reference for adding browser-level UI tests to Databricks Apps using Playwright and pytest. Applies to Flask apps and APX apps alike.

---

## Stack

```
pytest
pytest-playwright
playwright
uv dependency groups for test-only dependencies
```

The pytest-playwright plugin provides Playwright fixtures, browser contexts, and multi-browser options out of the box. This keeps the test toolchain in Python without adding a Node test stack.

### pyproject.toml

```toml
[dependency-groups]
dev = [
    "pytest>=8.0",
    "playwright>=1.50",
    "pytest-playwright>=0.7",
]
```

---

## Running Tests

```bash
# Install dependencies and browser
uv sync --group dev
uv run python -m playwright install chromium

# Run full UI suite
uv run pytest tests --browser chromium

# Retain traces and screenshots on failure
uv run pytest tests --browser chromium --tracing retain-on-failure --screenshot only-on-failure

# Run a single test file
uv run pytest tests/test_ui_flow.py --browser chromium

# View a trace artifact
uv run python -m playwright show-trace test-results/<trace.zip>

# Run real-backend smoke tests (requires credentials)
uv run pytest tests -m real_backend --browser chromium
```

CI runners may need Playwright system dependencies. Use this instead of the plain install:

```bash
uv run python -m playwright install --with-deps chromium
```

---

## Best Practices

**Test user-visible behavior.** Interact with visible controls and assert rendered results. Keep assertions focused on the rendered page.

**Keep tests isolated.** Each test gets a fresh browser context and does not depend on another test having already run.

**Prefer Playwright locators.** Use role, text, label, and explicit test IDs. Avoid selectors tied to CSS classes, DOM depth, or visual layout.

**Use web-first assertions.** These automatically wait and retry until the expected UI state appears, which eliminates timing flakes around async fetches and graph rendering.

**Use trace artifacts for CI debugging.** Playwright traces include actions, DOM snapshots, console output, network requests, and source locations. They are more useful than screenshots alone.

**Avoid real external systems in the core suite.** The daily fast suite should run against a mock backend. Real Neo4j and Databricks checks belong in a separate opt-in suite.

**Start with Chromium only.** Cross-browser coverage can be added once the core harness is stable.

---

## App Prerequisites

Before adding Playwright tests, confirm your app has:

- A way to run locally without external credentials. A mock mode or environment variable flag is the standard pattern.
- A startup command the test fixture can invoke on an unused local port.
- Stable element identifiers on workflow controls: accessible names or `data-testid` attributes.
- Known stable outputs in mock mode for assertion.

### Mock Mode: Flask

Set `USE_MOCK_BACKEND=true` as an environment variable and branch in the backend:

```python
USE_MOCK = os.getenv("USE_MOCK_BACKEND", "false").lower() == "true"

def search(signal_type, filters):
    if USE_MOCK:
        return _mock_search_results()
    return _real_search(signal_type, filters)
```

### Mock Mode: APX / FastAPI

Use a settings-based flag and override the service layer:

```python
# settings.py
class Settings(BaseSettings):
    use_mock_backend: bool = False

# router.py
@router.post("/api/search/rings")
def search_rings(settings: Settings = Depends(get_settings)):
    if settings.use_mock_backend:
        return _mock_rings()
    return _real_rings()
```

### Static Assets

Any third-party JS loaded from a CDN at runtime (Cytoscape, Chart.js) will cause headless tests to depend on external network availability. Vendor or locally serve these assets before making the test suite a required CI gate.

---

## File Layout

```
<app-directory>/
  tests/
    conftest.py         # server fixture: starts app in mock mode on a free port
    test_ui_flow.py     # end-to-end mock workflow test
    test_ui_contract.py # selector and state regression checks
  test-results/         # Playwright artifacts (gitignored)
  pyproject.toml        # includes dev dependency group
  .gitignore            # test-results/ must be covered
```

---

## Phase Checklist

### Phase 1: Foundation

- [ ] Add Playwright and pytest dev dependencies via `uv`.
- [ ] Add `tests/conftest.py` with a server fixture that starts the app in mock mode on a free port.
- [ ] Force `USE_MOCK_BACKEND=true` in the fixture. Override any `.env` values that could point to real services.
- [ ] Add a browser page fixture that uses the server base URL.
- [ ] Configure trace and screenshot defaults for failed tests.

Validation:
- `uv sync --group dev` succeeds.
- `uv run pytest --collect-only` discovers the UI tests.
- The app process is stopped after the test run.
- Tests complete without any external credentials.

### Phase 2: Selector Hardening

- [ ] Add `data-testid` attributes to stable workflow controls.
- [ ] Prefer accessible role and text locators where the accessible name is natural and stable.
- [ ] Use `data-testid` for repeated or ambiguous controls: checkboxes, modal buttons, progress steps.
- [ ] Name `data-testid` values after business intent, not visual position. For example: `ring-checkbox-RING-0041`, `load-selected`, `report-modal`.

Validation:
- Existing manual browser workflow still works.
- Playwright locators uniquely identify each target element.

### Phase 3: Core Workflow Test

- [ ] Implement the full mock workflow as a single end-to-end test.
- [ ] Assert known mock values rather than only checking element existence.
- [ ] Fail on browser console errors and failed application network responses.
- [ ] Capture a trace on failure.

Validation:
- `uv run pytest tests/test_ui_flow.py --browser chromium --tracing retain-on-failure` passes locally.
- `test-results/` contains useful artifacts when a test is intentionally failed.

### Phase 4: CI Integration

- [ ] Add a CI job that installs Python dependencies with `uv`.
- [ ] Install Chromium with system dependencies before running tests.
- [ ] Run the UI suite in headless Chromium.
- [ ] Upload `test-results/` artifacts on failure.
- [ ] Scope CI triggers to the app directory and the test workflow file.

Validation:
- CI runs the UI suite on every pull request touching the app.
- Failed runs expose trace artifacts for local replay.

### Phase 5: Real-Backend Smoke Tests (Optional)

- [ ] Add a separate pytest marker such as `@pytest.mark.real_backend`.
- [ ] Require explicit environment variables before running. Skip cleanly when they are absent.
- [ ] Keep assertions shallow: app boots, first workflow step completes, at least one result appears.
- [ ] Exclude from the default CI gate.

Validation:
- Suite skips cleanly when credentials are absent.
- Can be run manually with credentials present.

---

## Quality Bar

The test suite is ready for mandatory CI when:

- The default test path is deterministic and requires no external credentials.
- Tests drive the browser and assert visible outcomes. They do not call application APIs directly.
- Locators survive layout and CSS changes.
- Assertions use web-first waits rather than `sleep`.
- Failure output includes enough trace detail to debug without reproducing locally.
- Local commands and CI behavior are documented in the app README.

---

## Risks and Mitigations

| Risk | Mitigation |
|------|-----------|
| Async graph or chart rendering causes flakes | Assert surrounding UI state and stable data values. Avoid low-level canvas or SVG internals unless graph rendering is itself the test target. |
| CDN assets block headless tests | Vendor or locally serve all third-party JS before making the suite mandatory. |
| Real-backend tests fail due to credentials, data drift, or workspace availability | Keep real-backend checks opt-in and separated from the mock suite. |
| Selectors break during copy changes | Use accessible locators for user-visible contracts. Use `data-testid` for controls where copy is not part of the contract. |
| CI is slow because all browsers install | Start with Chromium only. Add Firefox or WebKit when browser-specific defects become a concern. |

---

## References

- [Playwright Best Practices](https://playwright.dev/docs/best-practices)
- [Playwright Python Pytest Plugin](https://playwright.dev/python/docs/test-runners)
- [Playwright Python Trace Viewer](https://playwright.dev/python/docs/trace-viewer)
- [Playwright Python CI](https://playwright.dev/python/docs/ci)
- [pytest documentation](https://docs.pytest.org/en/stable/)
