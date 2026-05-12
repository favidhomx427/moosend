"""Basic tests for the email automation tool (no network calls)."""

import csv
import tempfile
from pathlib import Path

from email_automation import EmailAutomation, load_contacts


def test_render_double_brace():
    out = EmailAutomation.render("Hello {{name}}!", {"name": "Alice"})
    assert out == "Hello Alice!"


def test_render_dollar_template():
    out = EmailAutomation.render("Hello ${name}!", {"name": "Bob"})
    assert out == "Hello Bob!"


def test_render_missing_var_is_safe():
    # safe_substitute leaves unknown placeholders intact
    out = EmailAutomation.render("Hi {{name}}, code {{missing}}", {"name": "A"})
    assert "Hi A" in out
    assert "${missing}" in out


def test_build_message_basic():
    tool = EmailAutomation("smtp.example.com", 587, "u@example.com", "pw")
    msg = tool.build_message(
        to_email="to@example.com",
        subject="Subject here",
        body_text="Plain body",
        body_html="<p>HTML body</p>",
        from_name="Sender",
    )
    assert msg["To"] == "to@example.com"
    assert msg["Subject"] == "Subject here"
    assert "Sender" in msg["From"]


def test_load_contacts():
    with tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["email", "name"])
        writer.writerow(["a@x.com", "A"])
        writer.writerow(["b@x.com", "B"])
        path = f.name
    try:
        contacts = load_contacts(path)
        assert len(contacts) == 2
        assert contacts[0]["email"] == "a@x.com"
        assert contacts[1]["name"] == "B"
    finally:
        Path(path).unlink()


def test_dry_run_sends_nothing():
    tool = EmailAutomation("smtp.example.com", 587, "u@example.com", "pw")
    results = tool.send_bulk(
        contacts=[{"email": "x@example.com", "name": "X"}],
        subject_template="Hi {{name}}",
        body_template="Hi {{name}}",
        dry_run=True,
    )
    assert results["sent"] == 1
    assert results["failed"] == 0


def test_invalid_email_is_skipped():
    tool = EmailAutomation("smtp.example.com", 587, "u@example.com", "pw")
    results = tool.send_bulk(
        contacts=[{"email": "not-an-email", "name": "X"}],
        subject_template="Hi",
        body_template="Hi",
        dry_run=True,
    )
    assert results["skipped"] == 1
    assert results["sent"] == 0


if __name__ == "__main__":
    # Allow running without pytest
    import inspect
    import sys

    funcs = [(n, f) for n, f in globals().items() if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in funcs:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as e:
            failed += 1
            print(f"FAIL {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"ERROR {name}: {type(e).__name__}: {e}")
    sys.exit(1 if failed else 0)
