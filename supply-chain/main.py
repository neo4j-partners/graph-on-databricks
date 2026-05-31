"""
Supply Chain Optimizer — interactive CLI entry point.

Usage:
    python main.py
    python main.py --question "Which suppliers have Critical risk?"
"""
import argparse
import json
import logging
import sys

from dotenv import load_dotenv

load_dotenv()  # Must be before any agents import

from agents.router import RouterAgent  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s — %(message)s",
)


def _pretty_print(result: dict) -> None:
    route = result.get("route", "?")
    from_cache = result.get("from_cache", False)
    cache_label = " [CACHED]" if from_cache else ""
    print(f"\n{'='*60}")
    print(f"  Route : {route.upper()}{cache_label}")
    print(f"{'='*60}")

    inner = result.get("result", {})
    if isinstance(inner, dict):
        answer = inner.get("answer", "")
        print(f"\n{answer}\n")

        queries = inner.get("queries") or inner.get("cypher_queries") or []
        if queries:
            print(f"  — {len(queries)} query/queries executed")
    else:
        print(inner)


def run_interactive(router: RouterAgent) -> None:
    print("\nSupply Chain Optimizer  (type 'exit' to quit)\n")
    while True:
        try:
            question = input("Question > ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nGoodbye.")
            break
        if question.lower() in ("exit", "quit", "q"):
            print("Goodbye.")
            break
        if not question:
            continue
        result = router.ask(question)
        _pretty_print(result)


def main() -> None:
    parser = argparse.ArgumentParser(description="Supply Chain Optimizer CLI")
    parser.add_argument("--question", "-q", help="One-shot question (skips interactive mode)")
    parser.add_argument("--json", action="store_true", help="Output raw JSON")
    args = parser.parse_args()

    router = RouterAgent()

    if args.question:
        result = router.ask(args.question)
        if args.json:
            print(json.dumps(result, indent=2, default=str))
        else:
            _pretty_print(result)
    else:
        run_interactive(router)


if __name__ == "__main__":
    main()
