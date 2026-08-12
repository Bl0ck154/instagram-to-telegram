from __future__ import annotations

import argparse
from dataclasses import replace

from .config import load_config
from .redaction import install_output_redaction
from .sync import SyncRunner


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync Instagram posts to Telegram.")
    parser.add_argument("--config", default="config.example.yml", help="Path to YAML or JSON config file.")
    parser.add_argument("--backend", choices=["instaloader", "browser", "curl_cffi", "apify", "auto"], help="Override configured sync backend.")
    parser.add_argument("--dry-run", action="store_true", help="Download posts and update state without sending to Telegram.")
    parser.add_argument("--initialize-only", action="store_true", help="Mark fetched posts as processed without sending to Telegram.")
    parser.add_argument("--diagnose-shortcode", help="Fetch and download one Apify post for media diagnostics without Telegram sending.")
    parser.add_argument("--validate", action="store_true", help="Validate config and exit without contacting Instagram.")
    args = parser.parse_args()

    config = load_config(args.config)
    install_output_redaction(config)

    if args.backend:
        config = replace(config, backend=args.backend)
    if args.dry_run:
        config = replace(config, dry_run=True)
    if args.initialize_only:
        config = replace(config, initialize_only=True)
    if args.validate:
        print(f"Config OK: {len(config.accounts)} enabled account(s), backend={config.backend}.")
        return
    if args.diagnose_shortcode:
        SyncRunner(config).diagnose_apify_shortcode(args.diagnose_shortcode)
        return

    SyncRunner(config).run()


if __name__ == "__main__":
    main()
