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
from collections import defaultdict
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass
from itertools import islice
from typing import Any

from nams_traffic.client import AppClient, TurnFailed, service_principal_client
from nams_traffic.scenarios import TurnRequest, build_requests

logger = logging.getLogger("nams_traffic")

Invoke = Callable[[TurnRequest, threading.Event], Any]


@dataclass
class Summary:
    ok: int = 0
    failed: int = 0
    skipped: int = 0
    seconds: float = 0.0

    @property
    def exit_code(self) -> int:
        return 1 if self.failed else 0


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
                    logger.info("ok     %s turn=%d %.1fs", request.session_id, request.turn, elapsed)
                    continue
                summary.failed += 1
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
    parser.add_argument("--dry-run", action="store_true", help="Print the plan and exit.")
    args = parser.parse_args(argv)
    for name in ("users", "sessions_per_user", "turns_per_session", "concurrency"):
        if getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be at least 1")
    if not args.dry_run and not args.app_url:
        parser.error("--app-url or $APP_URL is required unless --dry-run")
    return args


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
    logger.info(
        "done ok=%d failed=%d skipped=%d in %.0fs",
        summary.ok, summary.failed, summary.skipped, summary.seconds,
    )
    return summary.exit_code


if __name__ == "__main__":
    sys.exit(main())
