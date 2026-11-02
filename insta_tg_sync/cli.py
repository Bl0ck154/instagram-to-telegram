from __future__ import annotations

import argparse
from dataclasses import replace

from .config import load_config
from .redaction import install_output_redaction


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Instagram posts to Telegram.")
    parser.add_argument("--config", default="config.example.yml", help="Path to YAML or JSON config file.")
    parser.add_argument(
        "--backend",
        choices=["instaloader", "browser", "curl_cffi", "apify", "auto"],
        help="Override configured sync backend.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Download posts and update state without sending to Telegram.")
    parser.add_argument("--initialize-only", action="store_true", help="Mark fetched posts as processed without sending to Telegram.")
    parser.add_argument("--diagnose-shortcode", help="Fetch and download one Apify post for media diagnostics without Telegram sending.")
    parser.add_argument("--validate", action="store_true", help="Validate config and exit without contacting Instagram.")
    parser.add_argument(
        "--catch-up-hours", type=int,
        help="Manual-only catch-up window, 48-168 hours; dry-run first to review old posts.",
    )
    args = parser.parse_args()

    config = load_config(args.config)
    install_output_redaction(config)

    if args.backend:
        config = replace(config, backend=args.backend)
    if args.dry_run:
        config = replace(config, dry_run=True)
    if args.initialize_only:
        config = replace(config, initialize_only=True)
    if args.catch_up_hours is not None:
        if config.backend != "apify" or not 48 <= args.catch_up_hours <= 168:
            parser.error("--catch-up-hours requires Apify and a value between 48 and 168.")
        config = replace(config, apify=replace(config.apify, max_post_age_hours=args.catch_up_hours))
        print(f"Manual catch-up window: {args.catch_up_hours} hours (no automatic replay of older posts).")
    if args.validate:
        print(f"Config OK: {len(config.accounts)} enabled account(s), backend={config.backend}.")
        return

    if args.diagnose_shortcode:
        from .apify_sync import ApifySyncRunner

        ApifySyncRunner(config).diagnose_apify_shortcode(args.diagnose_shortcode)
        return

    if config.backend == "apify":
        from .apify_sync import ApifySyncRunner

        runner = ApifySyncRunner(config)
    else:
        try:
            from .sync import SyncRunner
        except ModuleNotFoundError as error:
            raise RuntimeError(
                f"Backend '{config.backend}' needs optional dependencies. "
                "Install them with: python -m pip install -r requirements-advanced.txt"
            ) from error
        runner = SyncRunner(config)

    runner.run()


if __name__ == "__main__":
    main()
