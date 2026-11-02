# Choose a deployment: private template, public template or fork

The quickest supported setup for most people is a **private repository created from this public template**. It keeps the regular GitHub Actions schedule and avoids the specific 60-day inactivity rule that GitHub applies to scheduled workflows in public repositories.

[Create a private repository from the template](https://github.com/new?template_owner=Bl0ck154&template_name=instagram-to-telegram&visibility=private) · [Open the setup wizard](https://bl0ck154.github.io/instagram-to-telegram/)

You still need your own **public Instagram profile**, **Telegram channel where your bot can post**, **Telegram BotFather token**, and **Apify API token**. No deployment can repost without this information. The setup wizard only generates public configuration; it never collects API tokens.

## Deployment choices

| Choice | GitHub's 60-day public inactivity cutoff | Actions and costs | Setup work |
| --- | --- | --- | --- |
| **Private copy from template (recommended)** | Not applicable to private repositories | Uses the owner's included GitHub Actions minutes; GitHub Free includes 2,000 minutes/month across eligible private workflows. Apify may also charge. | Create private template copy, add credentials/config, initialize once. |
| Public copy from template | Applies if the repository has no activity for 60 days | Standard GitHub-hosted Actions runners are free for public repos. Apify may also charge. | Same setup; check scheduled workflow status over time. |
| Public fork | Applies; scheduled workflows are disabled in public forks by default | Standard hosted Actions runners are free for public repos. Apify may also charge. | Must explicitly enable Actions/scheduled workflows, set credentials, initialize. |
| Public copy with community keepalive action | **Best effort**, not an official guarantee | Can avoid fake commits with API-based enable requests; additional third-party workflow or code and token permissions | Configure the chosen keepalive, audit its permissions, monitor that it still runs. |
| External Cloudflare Cron -> GitHub workflow_dispatch | Independent of GitHub's built-in schedule; GitHub workflow must stay enabled | Worker may fit within Cloudflare's free tier, but service limits change; Apify remains separate | Extra Worker, scoped GitHub token, monitoring, and a dispatch-only workflow configuration. |

### Recommended: private template copy

1. Select **Create private copy** in the [setup wizard](https://bl0ck154.github.io/instagram-to-telegram/). GitHub opens the template creation page with **Private** selected; verify the visibility before creating it. Choose the default branch only; you do not need other template branches.
2. Enter your Instagram profile and Telegram channel in the wizard. Copy the resulting `ACCOUNTS_JSON` into **Settings → Secrets and variables → Actions → Variables** of your own new repository.
3. Add `TELEGRAM_BOT_TOKEN` and `APIFY_TOKEN` as **Actions Secrets** (never Actions Variables or files committed to the repo). Make your bot a Telegram channel admin with permission to post.
4. In **Actions → Instagram to Telegram**, enable workflows if GitHub asks. Run with `initialize_only=true` once to baseline existing Instagram posts without publishing. Then run with `dry_run=true` to verify behavior without sending media. Check the log and state branch.
5. Leave the built-in schedule enabled; it checks approximately every six hours (runs can be delayed or dropped). New Instagram posts do not trigger a run.

This is the recommended path because it requires **no server, no external scheduler, no fake commits, and no personal-access token for cron**. Review your account's Actions billing/budget settings: private workflows use the account's compute allowance and can stop or incur charges if allowance/budget policy is exhausted. A private copy is also independent of upstream updates; your copy does not automatically receive future fixes.

### Public deployments and the 60-day problem

GitHub explicitly says scheduled workflows **in public repositories** are disabled after 60 days without repository activity. A scheduled check, a new Instagram post, or a Telegram message should **not** be relied on to reset the inactivity timer. We have not established that commits to the separate `sync-state` branch count. The original upstream repository currently has regular `main` development commits; a new public copy may have none.

For a public copy, choose one of the following:

- **Manual re-enable:** Open the copied repository's **Actions** tab, select **Instagram to Telegram**, and choose **Enable workflow** if disabled. This is simple, but requires someone to notice downtime.
- **Community keepalive:** You may evaluate [Keepalive Workflow](https://github.com/marketplace/actions/keepalive-workflow) or [scheduled-workflow-activity-action](https://github.com/WaterLemons2k/scheduled-workflow-activity-action). These use GitHub API enable/keepalive mechanisms; some alternatives create dummy commits. They are optional, **not installed by our template**, and not guaranteed by GitHub to prevent disabling. Review third-party code, requested `actions: write` / `contents: write` permissions, pinned versions, and whether they still work if GitHub has already disabled the scheduled trigger. A self-scheduled keepalive cannot wake itself if it is already disabled.
- **External cron (advanced):** A Cloudflare Worker with a Cron Trigger can call GitHub's `workflow_dispatch` API using a fine-grained token scoped to **one repository** with appropriate Actions write access. For this mode, remove the GitHub `schedule` trigger in your own copy, use an explicit dispatch-only workflow, and monitor results and token expiry. The public-template schedule is therefore no longer responsible for triggering runs. This is **an integration option to build yourself**, not a feature already provided by this repository or the hosted wizard. Do not put the GitHub token in public files or browser JavaScript.

**Fork or template?** A public fork of this repository remains public, and GitHub disables scheduled workflows in public forks by default. Creating a new repository via **Use this template** lets you select Private and start with fresh history. Neither option copies another person's Secrets. A newly created repository **will not work immediately without your credentials and one-time setup**.

### GitHub Actions and Apify pricing

Public repositories running standard GitHub-hosted runners generally receive free Actions execution. Private repositories consume the owner's monthly allowance; GitHub Free lists **2,000 minutes/month**. Four checks/day is roughly 120 checks/month, but each check can take different time and other repositories also consume your allowance. GitHub Actions execution cost is **separate** from Apify's actor usage and pricing. Do not assume unlimited free execution.

### References

- [GitHub: Disabling and enabling workflows](https://docs.github.com/en/actions/how-tos/manage-workflow-runs/disable-and-enable-workflows)
- [GitHub: Create from a template](https://docs.github.com/en/repositories/creating-and-managing-repositories/creating-a-repository-from-a-template)
- [GitHub: GitHub Actions billing](https://docs.github.com/en/billing/concepts/product-billing/github-actions)
- [GitHub: Events that trigger workflows](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)
- [Cloudflare: Cron Triggers](https://developers.cloudflare.com/workers/configuration/cron-triggers/)
