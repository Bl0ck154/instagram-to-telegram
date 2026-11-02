"""Manually resolve uncertain Telegram deliveries after checking the channel."""
from __future__ import annotations

import argparse
import os
from pathlib import Path

from .state import StateStore


def resolve(path: Path, username: str, shortcode: str, resolution: str) -> None:
    if resolution not in {"delivered", "retry"}:
        raise ValueError("Resolution must be delivered or retry.")
    if not username.strip() or not shortcode.strip():
        raise ValueError("Username and shortcode are required.")
    state = StateStore(path)
    state.load()
    if not state.has_account(username):
        raise ValueError("Account not found in state. No changes made.")
    if not state.resolve_uncertain(username, shortcode, delivered=resolution == "delivered"):
        raise ValueError("No uncertain delivery for this account and shortcode. No changes made.")
    state.save()
    if resolution == "delivered":
        print("Operator confirmed delivery; post marked processed and quarantine cleared.")
    else:
        print("Operator confirmed retry is safe; quarantine cleared. This DOES NOT send a post.")
        print("Run a manual dry-run to check eligibility before any live sync.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--state-file", type=Path, default=Path("data/state.json"))
    parser.add_argument("--username", default=os.environ.get("RESOLVE_USERNAME", ""))
    parser.add_argument("--shortcode", default=os.environ.get("RESOLVE_SHORTCODE", ""))
    parser.add_argument(
        "--resolution", choices=("delivered", "retry"),
        default=os.environ.get("RESOLVE_ACTION"),
    )
    args = parser.parse_args()
    if args.resolution is None:
        parser.error("Resolution is required.")
    resolve(args.state_file, args.username, args.shortcode, args.resolution)


if __name__ == "__main__":
    main()
