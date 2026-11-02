"""Regression checks for private-first deployment documentation and static wizard."""
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent

class AnchorParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.links = []
        self.inputs = []
        self.ids = set()

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "a" and "href" in attrs:
            self.links.append(attrs["href"])
        if tag == "input":
            self.inputs.append(attrs)


def test_template_links_are_valid_and_private_first():
    source = (ROOT / "docs/index.html").read_text()
    doc = AnchorParser()
    doc.feed(source)
    create = [u for u in doc.links if "github.com/new?" in u]
    assert len(create) == 2
    args_private = parse_qs(urlparse(create[0]).query)
    assert args_private == {
        "template_owner": ["Bl0ck154"],
        "template_name": ["instagram-to-telegram"],
        "visibility": ["private"],
    }
    assert parse_qs(urlparse(create[1]).query)["visibility"] == ["public"]
    assert {"repo-url", "repo-secrets", "repo-variables", "repo-workflow"} <= doc.ids


def test_wizard_builds_client_side_shortcuts_without_tokens():
    source = (ROOT / "docs/index.html").read_text()
    assert "/settings/secrets/actions" in source
    assert "/settings/variables/actions" in source
    assert "/actions/workflows/instagram-to-telegram.yml" in source
    assert 'repoInput.addEventListener("input",updateRepositoryLinks)' in source
    assert 'link.href=base+path;' in source
    assert 'link.hidden=false;' in source
    parser = AnchorParser()
    parser.feed(source)
    assert not any(i.get("name") in {"APIFY_TOKEN", "TELEGRAM_BOT_TOKEN"}
                   for i in parser.inputs)


def test_doc_explains_every_deployment_and_limit():
    comparison = (ROOT / "docs/DEPLOYMENT.md").read_text()
    readme = (ROOT / "README.md").read_text()
    setup = (ROOT / "docs/SETUP.md").read_text()
    for topic in ("Private copy", "Public copy", "Public fork",
                  "keepalive", "Cloudflare", "60 days"):
        assert topic.lower() in comparison.lower()
    assert "2,000" in comparison
    assert "does not automatically" in comparison.lower() or "will not work immediately" in comparison.lower()
    assert "visibility=private" in readme
    assert "docs/DEPLOYMENT.md" in readme
    assert "DEPLOYMENT.md" in setup
    assert "initialize_only" in readme


def test_wizard_no_external_cron_wired_in_default_workflow():
    workflow = (ROOT / ".github/workflows/instagram-to-telegram.yml").read_text()
    assert 'cron: "17 */6 * * *"' in workflow
    assert "workflow_dispatch:" in workflow
    assert "cloudflare" not in workflow.lower()
