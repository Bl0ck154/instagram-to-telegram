"""Privacy-safe GitHub Actions usage report."""
from __future__ import annotations
import json
import os
from pathlib import Path

def build_report(path: Path) -> str:
    if not path.exists():
        return "## Instagram → Telegram" + chr(10) + "No state data available." + chr(10)
    data = json.loads(path.read_text(encoding="utf-8"))
    stats = data.get("stats") or {}
    records = [stats[day] for day in sorted(stats)[-7:]]
    keys = ("checks", "fetched", "published", "skipped", "dry_runs", "errors", "estimated_apify_results", "uncertain")
    totals = {key: sum(int(bucket.get(key, 0)) for bucket in records) for key in keys}
    unresolved = sum(len(account.get("uncertain", {}))
                     for account in (data.get("accounts") or {}).values()
                     if isinstance(account, dict))
    rows = ["## Instagram → Telegram · last 7 recorded days", "",
            "| Metric | Count |", "|:--|--:|"]
    rows.extend(f"| {key.replace('_', ' ').title()} | {value} |" for key, value in totals.items())
    rows.extend([
        f"| Unresolved Telegram delivery outcomes | {unresolved} |",
        f"| Consecutive failed runs | {int((data.get('health') or {}).get('consecutive_failures', 0))} |",
        "",
        "Apify results are locally estimated requested limits, not vendor-billed charges.",
        "Delivery outcomes marked uncertain require manual checking in Telegram.",
    ])
    return chr(10).join(rows) + chr(10)

def main() -> None:
    report = build_report(Path("data/state.json"))
    print(report)
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with open(os.environ["GITHUB_STEP_SUMMARY"], "a", encoding="utf-8") as handle:
            handle.write(report)

if __name__ == "__main__":
    main()
