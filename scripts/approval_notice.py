"""Notify the named approver when a review reaches the approval step.

Slack and email are off unless their settings are set. A failed send is logged
and does not change the review. data-boundaries.mdc: a notice carries the vendor
name, the decision needed, the review link, and the approver name and address.
It never carries bank details, EIN/tax IDs, SSNs, passwords, or contract contents.
"""

import json
import os
import smtplib
import sys
import urllib.request
from email.message import EmailMessage
from pathlib import Path

SLACK_URL = "APPROVAL_SLACK_WEBHOOK_URL"
SMTP_HOST = "APPROVAL_SMTP_HOST"
SMTP_PORT = "APPROVAL_SMTP_PORT"
SMTP_USER = "APPROVAL_SMTP_USER"
SMTP_PASSWORD = "APPROVAL_SMTP_PASSWORD"
SMTP_FROM = "APPROVAL_SMTP_FROM"
REVIEW_BASE_URL = "APPROVAL_REVIEW_BASE_URL"
SMTP_KEYS = (SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM)
# Tests point these at a file or a forced error so they never open a socket.
CAPTURE = "APPROVAL_NOTICE_CAPTURE"
FAIL = "APPROVAL_NOTICE_FAIL"
TIMEOUT = 5


def _log(message):
    print(message, file=sys.stderr)


def _get(env, key):
    return (env.get(key) or "").strip()


def read_settings(env=None):
    env = os.environ if env is None else env
    missing = [key for key in SMTP_KEYS if not _get(env, key)]
    email = None
    reason = "SMTP settings are unset"
    if not missing:
        try:
            port = int(_get(env, SMTP_PORT))
        except ValueError:
            reason = "APPROVAL_SMTP_PORT is not a number"
        else:
            email = {
                "host": _get(env, SMTP_HOST),
                "port": port,
                "user": _get(env, SMTP_USER),
                "password": _get(env, SMTP_PASSWORD),
                "from": _get(env, SMTP_FROM),
            }
    elif len(missing) < len(SMTP_KEYS):
        reason = "SMTP settings are incomplete"
    return {
        "slack_url": _get(env, SLACK_URL),
        "email": email,
        "email_reason": reason,
        "review_base": _get(env, REVIEW_BASE_URL),
    }


def review_link(base, request_id):
    base = (base or "").rstrip("/")
    return f"{base}/{request_id}" if base else request_id


def notice_body(vendor, role, link, name, address):
    label = name or "no approver named in config"
    who = f"{label} <{address}>" if address else label
    return (
        f"Vendor: {vendor}\n"
        f"Decision needed: {role} approval\n"
        f"Review: {link}\n"
        f"Approver: {who}\n"
    )


def _vendor(ticket):
    field = (ticket.get("intake") or {}).get("vendor_legal_name") or {}
    if isinstance(field, dict):
        return field.get("value") or "unknown vendor"
    return field or "unknown vendor"


def _approver_email(config, role):
    emails = config.get("approver_emails") or {}
    return (emails.get(role) or "").strip()


def _held(channel):
    failed = {part.strip() for part in os.environ.get(FAIL, "").split(",") if part.strip()}
    if channel in failed:
        raise OSError(f"{channel} transport failed")
    path = os.environ.get(CAPTURE, "").strip()
    return path


def _capture(path, payload):
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a") as handle:
        handle.write(json.dumps(payload) + "\n")


def post_slack(url, text):
    path = _held("slack")
    if path:
        _capture(path, {"channel": "slack", "text": text})
        return
    payload = json.dumps({"text": text}).encode()
    request = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        response.read()


def send_email(settings, to_addr, subject, body):
    path = _held("email")
    if path:
        _capture(path, {"channel": "email", "to": to_addr, "subject": subject, "body": body})
        return
    message = EmailMessage()
    message["From"] = settings["from"]
    message["To"] = to_addr
    message["Subject"] = subject
    message.set_content(body)
    with smtplib.SMTP(settings["host"], settings["port"], timeout=TIMEOUT) as smtp:
        smtp.ehlo()
        smtp.starttls()
        smtp.ehlo()
        smtp.login(settings["user"], settings["password"])
        smtp.send_message(message)


def _attempt(action, log, what):
    try:
        action()
    except Exception as error:
        log(f"approval notice: {what}: {type(error).__name__}")


def notify_requested(ticket, roles, config, log=None):
    if not roles:
        return
    log = log or _log
    settings = read_settings()
    if not settings["slack_url"]:
        log("approval notice: slack skipped, APPROVAL_SLACK_WEBHOOK_URL is unset")
    if not settings["email"]:
        log(f"approval notice: email skipped, {settings['email_reason']}")
    if not settings["slack_url"] and not settings["email"]:
        return
    if not settings["review_base"]:
        log("approval notice: APPROVAL_REVIEW_BASE_URL is unset")

    vendor = _vendor(ticket)
    request_id = ticket.get("request_id") or ""
    link = review_link(settings["review_base"], request_id)
    subject = f"Vendor review: {vendor} - decision needed"
    for role in roles:
        entry = (ticket.get("approvers") or {}).get(role) or {}
        name = entry.get("name") or (config.get("approvers") or {}).get(role)
        address = _approver_email(config, role)
        body = notice_body(vendor, role, link, name, address)
        if settings["slack_url"]:
            _attempt(lambda text=body: post_slack(settings["slack_url"], text), log,
                     f"slack failed for {request_id} {role}")
        if not settings["email"]:
            continue
        if not address:
            log(f"approval notice: email skipped for {role}, no address in company config")
            continue
        _attempt(lambda to=address, text=body: send_email(settings["email"], to, subject, text),
                 log, f"email failed for {request_id} {role}")
