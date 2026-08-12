import io

from insta_tg_sync.redaction import RedactingTextIO


def test_redaction_removes_configured_literals_and_shortcodes():
    output = io.StringIO()
    stream = RedactingTextIO(
        output,
        ["private_account", "@private_chat", "secret-token", "http://user:pass@proxy:9000"],
    )

    stream.write(
        "Checking @private_account; chat=@private_chat; token=secret-token; "
        "proxy=http://user:pass@proxy:9000; post ABC123; "
        "url=https://www.instagram.com/p/XYZ789/"
    )

    value = output.getvalue()
    assert "private_account" not in value
    assert "@private_chat" not in value
    assert "secret-token" not in value
    assert "user:pass" not in value
    assert "ABC123" not in value
    assert "XYZ789" not in value
    assert "<redacted>" in value
