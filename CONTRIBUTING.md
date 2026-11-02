# Contributing

Issues, bug reports and focused pull requests are welcome.

## Before opening a PR

- Search existing [issues](../../issues) and pull requests.
- For a user-facing change, update the README or `docs/SETUP.md`.
- Keep the default Apify + Telegram Bot API path lightweight. Advanced backends should remain optional.
- Never commit real tokens, Instagram sessions, private media or runtime state.
- Run `python -m pip install -r requirements-dev.txt` and `python -m pytest -q`.

If you are changing timestamp handling, state persistence or publishing, add a regression test. Changes to the scheduled workflow should preserve the default six-hour cadence and avoid unnecessary GitHub Actions usage.

## Pull request checklist

- [ ] Tests pass
- [ ] No user data, tokens or sessions in the diff
- [ ] No unexpected changes to scheduled behavior or API spending
- [ ] Documentation updated where needed

For security findings, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.
