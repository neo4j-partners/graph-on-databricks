"""Generate synthetic analyst traffic against the deployed graph agent so NAMS fills with
conversations, entities, and reasoning traces.

Sessions run in parallel, one per worker. The turns inside a session run in order.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
import time
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from itertools import islice
from pathlib import Path
from typing import Any

from nams_traffic.client import AppClient, TurnFailed, service_principal_client
from nams_traffic.scenarios import TurnRequest, build_requests
from nams_traffic.verify import DEFAULT_ENDPOINT, verify_stored, wait_until_ready

logger = logging.getLogger("nams_traffic")

Invoke = Callable[[TurnRequest, threading.Event], Any]

EXIT_TURNS_FAILED = 1
EXIT_NAMS_SHORT = 2


@dataclass
class Summary:
    ok: int = 0
    failed: int = 0
    skipped: int = 0
    seconds: float = 0.0
    ok_by_session: Counter[str] = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)
    # Turns NAMS did not store, per session. None when the stored count was not checked.
    missing: dict[str, int] | None = None

    @property
    def exit_code(self) -> int:
        """0 on success, 1 when a turn failed or was skipped, 2 when NAMS stored too few."""
        if self.failed or self.skipped:
            return EXIT_TURNS_FAILED
        return EXIT_NAMS_SHORT if self.missing else 0


def run_traffic(
    requests: list[TurnRequest],
    invoke: Invoke,
    *,
    concurrency: int,
    retry_attempts: int = 1,
    continue_after_error: bool = False,
    stop: threading.Event | None = None,
) -> Summary:
    """Run all sessions with at most ``concurrency`` in flight.

    ``retry_attempts`` is the total number of tries per turn. A retry reuses the turn's
    invocation id, so the runtime treats it as the same invocation.
    """
    stop = stop or threading.Event()
    sessions: dict[str, list[TurnRequest]] = defaultdict(list)
    for request in requests:
        sessions[request.session_id].append(request)

    summary = Summary()
    lock = threading.Lock()
    started = time.monotonic()

    def run_session(turns: list[TurnRequest]) -> None:
        for index, request in enumerate(turns):
            if stop.is_set():
                with lock:
                    summary.skipped += len(turns) - index
                return
            turn_started = time.monotonic()
            error = _invoke_with_retries(invoke, request, stop, retry_attempts)
            elapsed = time.monotonic() - turn_started
            with lock:
                if error is None:
                    summary.ok += 1
                    summary.ok_by_session[request.session_id] += 1
                    logger.info("ok     %s turn=%d %.1fs", request.session_id, request.turn, elapsed)
                    continue
                summary.failed += 1
                summary.errors.append(f"{request.session_id} turn={request.turn}: {error}")
                logger.error("failed %s turn=%d: %s", request.session_id, request.turn, error)
            if not continue_after_error:
                stop.set()

    pending: set[Future[None]] = set()
    queue = iter(sessions.values())
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        try:
            # Sliding window: keep `concurrency` sessions queued so stopping stays responsive.
            pending = {pool.submit(run_session, turns) for turns in islice(queue, concurrency)}
            while pending:
                done, pending = wait(pending, return_when=FIRST_COMPLETED)
                for future in done:
                    future.result()
                    if not stop.is_set() and (turns := next(queue, None)) is not None:
                        pending.add(pool.submit(run_session, turns))
        except KeyboardInterrupt:
            stop.set()
            logger.warning("interrupted, finishing in-flight turns")
    summary.skipped += sum(len(turns) for turns in queue)
    summary.seconds = time.monotonic() - started
    return summary


def _invoke_with_retries(
    invoke: Invoke, request: TurnRequest, stop: threading.Event, attempts: int
) -> TurnFailed | None:
    error: TurnFailed | None = None
    for attempt in range(1, max(attempts, 1) + 1):
        try:
            invoke(request, stop)
            return None
        except TurnFailed as failure:
            error = failure
            if stop.is_set():
                break
            logger.warning(
                "attempt %d/%d failed %s turn=%d: %s",
                attempt, attempts, request.session_id, request.turn, failure,
            )
    return error


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--app-url",
        default=os.environ.get("APP_URL"),
        help="Deployed app URL. Defaults to $APP_URL. Not needed with --dry-run.",
    )
    parser.add_argument("--profile", help="Databricks profile. Omit inside a Databricks Job.")
    parser.add_argument(
        "--credentials-scope",
        help="Secret scope with client-id and client-secret of a service principal to call the "
        "app as. Needed in a Databricks Job, whose own token the app rejects.",
    )
    parser.add_argument("--users", type=int, default=20)
    parser.add_argument("--sessions-per-user", type=int, default=3)
    parser.add_argument("--turns-per-session", type=int, default=4)
    parser.add_argument("--concurrency", type=int, default=4)
    parser.add_argument("--timeout", type=float, default=300, help="Seconds allowed per turn.")
    parser.add_argument(
        "--retry-attempts",
        type=int,
        default=1,
        help="Total tries per turn. Retries reuse the invocation id.",
    )
    parser.add_argument("--continue-after-error", action="store_true")
    parser.add_argument(
        "--run-id",
        default=uuid.uuid4().hex[:8],
        help="Names the users and sessions. Rerunning the same id replays stored invocations.",
    )
    parser.add_argument(
        "--verify-nams",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="After the run, count the conversations NAMS stored for this run and fail if any "
        "turn is missing. Needs MEMORY_API_KEY in the environment or a .env file. Default: on "
        "when the key is found, off when it is not.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print the plan and exit.")
    args = parser.parse_args(argv)
    for name in ("users", "sessions_per_user", "turns_per_session", "concurrency"):
        if getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be at least 1")
    if not args.dry_run and not args.app_url:
        parser.error("--app-url or $APP_URL is required unless --dry-run")
    return args


def find_memory_settings(
    env: Mapping[str, str], search_dirs: Iterable[Path]
) -> tuple[str, str] | None:
    """Return (api_key, endpoint). The environment wins over a .env file in any search dir."""
    merged: dict[str, str] = {}
    for directory in search_dirs:
        merged.update(_read_env_file(directory / ".env"))
    merged.update(env)
    key = merged.get("MEMORY_API_KEY", "")
    if not key:
        return None
    return key, merged.get("MEMORY_ENDPOINT") or DEFAULT_ENDPOINT


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        values[name.removeprefix("export ").strip()] = value.strip().strip("'\"")
    return values


def report(summary: Summary) -> None:
    """Print every failure and every turn NAMS lost, so none is buried in the run log."""
    for error in summary.errors:
        logger.error("FAILED %s", error)
    for session, count in sorted((summary.missing or {}).items()):
        logger.error(
            "NOT STORED %s: %d of %d turn(s) missing from NAMS",
            session, count, summary.ok_by_session[session],
        )


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", stream=sys.stdout
    )
    args = parse_args(argv)
    requests = build_requests(
        args.users, args.sessions_per_user, args.turns_per_session, args.run_id
    )
    logger.info(
        "run_id=%s users=%d sessions=%d turns=%d concurrency=%d",
        args.run_id,
        args.users,
        args.users * args.sessions_per_user,
        len(requests),
        args.concurrency,
    )
    if args.dry_run:
        for request in requests[:5]:
            logger.info("%s turn=%d: %s", request.session_id, request.turn, request.prompt)
        return 0

    settings = find_memory_settings(os.environ, [Path.cwd().parent, Path.cwd()])
    if args.verify_nams and settings is None:
        logger.error("--verify-nams needs MEMORY_API_KEY in the environment or a .env file")
        return EXIT_TURNS_FAILED
    verify = settings if args.verify_nams is not False else None
    if verify is None:
        logger.warning("NAMS stored count will not be checked: no MEMORY_API_KEY or --no-verify-nams")

    if verify is not None:
        try:
            wait_until_ready(verify[0], endpoint=verify[1])
        except (TimeoutError, OSError) as error:
            logger.error("NAMS is not ready, so no turns were sent: %s", error)
            return EXIT_NAMS_SHORT

    from databricks.sdk import WorkspaceClient

    workspace = WorkspaceClient(profile=args.profile)
    if args.credentials_scope:
        workspace = service_principal_client(workspace, args.credentials_scope)
    client = AppClient(args.app_url, workspace, timeout=args.timeout)
    try:
        summary = run_traffic(
            requests,
            client.invoke,
            concurrency=args.concurrency,
            retry_attempts=args.retry_attempts,
            continue_after_error=args.continue_after_error,
        )
    finally:
        client.close()
    if verify is not None and summary.ok_by_session:
        api_key, endpoint = verify
        try:
            summary.missing = verify_stored(
                summary.ok_by_session, f"nams-load-{args.run_id}-", api_key, endpoint=endpoint
            )
        except Exception as error:  # noqa: BLE001 - an unreachable NAMS must fail the run
            logger.error("could not check the NAMS stored count: %s", error)
            return EXIT_NAMS_SHORT
        stored = sum(summary.ok_by_session.values()) - sum(summary.missing.values())
        logger.info("NAMS stored %d of %d completed turn(s)", stored, summary.ok)
    logger.info(
        "done ok=%d failed=%d skipped=%d in %.0fs",
        summary.ok, summary.failed, summary.skipped, summary.seconds,
    )
    report(summary)
    return summary.exit_code


if __name__ == "__main__":
    sys.exit(main())
