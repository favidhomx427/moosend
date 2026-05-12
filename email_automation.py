"""
Simple Email Automation Tool
----------------------------
Send personalized bulk emails from a CSV contact list using customizable templates.

Features:
  - SMTP support (Gmail, Outlook, Yahoo, custom)
  - HTML + plain text emails
  - Personalization via Jinja2-style placeholders (e.g. {{name}})
  - CSV-driven recipient list
  - File attachments
  - Rate limiting and dry-run mode
  - Detailed logging
"""

import argparse
import csv
import logging
import mimetypes
import os
import smtplib
import sys
import time
from email.message import EmailMessage
from pathlib import Path
from string import Template

from dotenv import load_dotenv

# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("email_automation.log"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Core class
# ---------------------------------------------------------------------------
class EmailAutomation:
    """Send templated bulk emails over SMTP."""

    def __init__(
        self,
        smtp_server: str,
        smtp_port: int,
        username: str,
        password: str,
        use_tls: bool = True,
    ):
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.username = username
        self.password = password
        self.use_tls = use_tls
        self.server = None

    # ---- connection lifecycle ----
    def connect(self):
        """Open SMTP connection."""
        log.info(f"Connecting to {self.smtp_server}:{self.smtp_port} ...")
        if self.use_tls:
            self.server = smtplib.SMTP(self.smtp_server, self.smtp_port, timeout=30)
            self.server.starttls()
        else:
            self.server = smtplib.SMTP_SSL(self.smtp_server, self.smtp_port, timeout=30)
        self.server.login(self.username, self.password)
        log.info("SMTP login successful.")

    def disconnect(self):
        if self.server:
            try:
                self.server.quit()
            except Exception:
                pass
            self.server = None
            log.info("SMTP connection closed.")

    # ---- template rendering ----
    @staticmethod
    def render(template_text: str, context: dict) -> str:
        """Render a template using ${var} or {{var}} placeholders."""
        # Convert {{var}} to ${var} so we can use string.Template (safer than format)
        normalized = template_text.replace("{{", "${").replace("}}", "}")
        return Template(normalized).safe_substitute(context)

    # ---- email building ----
    def build_message(
        self,
        to_email: str,
        subject: str,
        body_text: str,
        body_html: str | None = None,
        from_name: str | None = None,
        attachments: list[str] | None = None,
        reply_to: str | None = None,
    ) -> EmailMessage:
        msg = EmailMessage()
        sender = f"{from_name} <{self.username}>" if from_name else self.username
        msg["From"] = sender
        msg["To"] = to_email
        msg["Subject"] = subject
        if reply_to:
            msg["Reply-To"] = reply_to

        msg.set_content(body_text)
        if body_html:
            msg.add_alternative(body_html, subtype="html")

        for path in attachments or []:
            p = Path(path)
            if not p.exists():
                log.warning(f"Attachment not found, skipping: {path}")
                continue
            ctype, encoding = mimetypes.guess_type(p)
            if ctype is None or encoding is not None:
                ctype = "application/octet-stream"
            maintype, subtype = ctype.split("/", 1)
            with open(p, "rb") as f:
                msg.add_attachment(
                    f.read(), maintype=maintype, subtype=subtype, filename=p.name
                )
        return msg

    # ---- sending ----
    def send(self, msg: EmailMessage):
        if not self.server:
            raise RuntimeError("SMTP not connected. Call connect() first.")
        self.server.send_message(msg)

    def send_bulk(
        self,
        contacts: list[dict],
        subject_template: str,
        body_template: str,
        html_template: str | None = None,
        from_name: str | None = None,
        attachments: list[str] | None = None,
        reply_to: str | None = None,
        delay: float = 1.0,
        dry_run: bool = False,
    ) -> dict:
        """Send personalized emails to a list of contact dicts.

        Each contact must contain an 'email' key. Other keys become template vars.
        """
        results = {"sent": 0, "failed": 0, "skipped": 0, "errors": []}

        if not dry_run:
            self.connect()

        try:
            for i, contact in enumerate(contacts, start=1):
                to_email = (contact.get("email") or "").strip()
                if not to_email or "@" not in to_email:
                    log.warning(f"[{i}] Skipping invalid email: {contact}")
                    results["skipped"] += 1
                    continue

                subject = self.render(subject_template, contact)
                body = self.render(body_template, contact)
                html = self.render(html_template, contact) if html_template else None

                msg = self.build_message(
                    to_email=to_email,
                    subject=subject,
                    body_text=body,
                    body_html=html,
                    from_name=from_name,
                    attachments=attachments,
                    reply_to=reply_to,
                )

                if dry_run:
                    log.info(f"[DRY-RUN {i}] Would send to {to_email}: {subject!r}")
                    results["sent"] += 1
                    continue

                try:
                    self.send(msg)
                    log.info(f"[{i}] Sent to {to_email}")
                    results["sent"] += 1
                except Exception as e:
                    log.error(f"[{i}] Failed to send to {to_email}: {e}")
                    results["failed"] += 1
                    results["errors"].append({"email": to_email, "error": str(e)})

                if delay > 0 and i < len(contacts):
                    time.sleep(delay)
        finally:
            if not dry_run:
                self.disconnect()

        return results


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def load_contacts(csv_path: str) -> list[dict]:
    """Load contacts from a CSV file. Must have an 'email' column."""
    path = Path(csv_path)
    if not path.exists():
        raise FileNotFoundError(f"Contacts file not found: {csv_path}")
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if "email" not in (reader.fieldnames or []):
            raise ValueError("CSV must contain an 'email' column.")
        return [row for row in reader]


def load_template(path: str) -> str:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Template not found: {path}")
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def main():
    load_dotenv()

    parser = argparse.ArgumentParser(
        description="Send personalized bulk emails from a CSV contact list."
    )
    parser.add_argument("--contacts", required=True, help="Path to CSV file of contacts.")
    parser.add_argument("--subject", required=True, help="Subject template string.")
    parser.add_argument("--body", required=True, help="Path to plain-text body template.")
    parser.add_argument("--html", help="Path to HTML body template (optional).")
    parser.add_argument("--from-name", help="Display name shown in the From field.")
    parser.add_argument("--reply-to", help="Reply-To address (optional).")
    parser.add_argument(
        "--attach", action="append", default=[], help="Attachment path (repeatable)."
    )
    parser.add_argument(
        "--delay", type=float, default=1.0, help="Seconds between emails (default: 1.0)."
    )
    parser.add_argument(
        "--dry-run", action="store_true", help="Render and log emails without sending."
    )
    args = parser.parse_args()

    # Required env vars
    required = ["SMTP_SERVER", "SMTP_PORT", "SMTP_USERNAME", "SMTP_PASSWORD"]
    missing = [k for k in required if not os.getenv(k)]
    if missing:
        log.error(f"Missing env vars: {', '.join(missing)}. See .env.example.")
        sys.exit(1)

    contacts = load_contacts(args.contacts)
    body_template = load_template(args.body)
    html_template = load_template(args.html) if args.html else None

    log.info(f"Loaded {len(contacts)} contacts from {args.contacts}")

    tool = EmailAutomation(
        smtp_server=os.getenv("SMTP_SERVER"),
        smtp_port=int(os.getenv("SMTP_PORT")),
        username=os.getenv("SMTP_USERNAME"),
        password=os.getenv("SMTP_PASSWORD"),
        use_tls=os.getenv("SMTP_USE_TLS", "true").lower() == "true",
    )

    results = tool.send_bulk(
        contacts=contacts,
        subject_template=args.subject,
        body_template=body_template,
        html_template=html_template,
        from_name=args.from_name or os.getenv("FROM_NAME"),
        attachments=args.attach,
        reply_to=args.reply_to,
        delay=args.delay,
        dry_run=args.dry_run,
    )

    log.info(
        f"Done. Sent: {results['sent']}, Failed: {results['failed']}, "
        f"Skipped: {results['skipped']}"
    )
    if results["errors"]:
        log.info(f"Errors: {results['errors']}")


if __name__ == "__main__":
    main()
