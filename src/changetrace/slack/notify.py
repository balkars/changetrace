"""Slack Block Kit messages for PRs and deployments, posted to an incoming webhook.

Slack must never fail a command: `post_webhook` swallows every error. The webhook URL is
a secret and is never printed.
"""
from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from typing import Callable

from ..check import Finding
from ..deploy import DeployReport
from ..records import Record

_TIMEOUT_SECONDS = 10
_SECTION_LIMIT = 2900  # Slack rejects section text over 3000 characters.
_HEADER_LIMIT = 150


def _clip(text: str, limit: int = _SECTION_LIMIT) -> str:
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def _header(text: str) -> dict:
    return {"type": "header", "text": {"type": "plain_text", "text": _clip(text, _HEADER_LIMIT)}}


def _section(text: str) -> dict:
    return {"type": "section", "text": {"type": "mrkdwn", "text": _clip(text)}}


def _context(*texts: str) -> dict:
    return {"type": "context", "elements": [{"type": "mrkdwn", "text": _clip(t)} for t in texts]}


def _repo_link(repo_url: str) -> str | None:
    return f"<{repo_url}|{repo_url.removeprefix('https://')}>" if repo_url else None


def _watch_out(record: Record) -> str:
    text = record.section("Watch out")
    return f":warning: Watch out: {text}" if text else ""


def pr_payload(pr: dict, records: list[Record], findings: list[Finding], repo_url: str, project: str = "") -> dict:
    title = f"PR #{pr['number']} · {pr['title']}"
    who = " · ".join(x for x in (pr.get("author") or "", project) if x)
    context = [t for t in (who, _repo_link(repo_url)) if t]
    blocks: list[dict] = [_header(title)]
    if context:
        blocks.append(_context(*context))
    if pr.get("url"):
        blocks.append(_section(f"<{pr['url']}|Open pull request>"))
    if records:
        for r in records:
            lines = [f"*{r.id} · {r.title}*", r.section("Decided"), _watch_out(r)]
            blocks.append(_section("\n".join(x for x in lines if x)))
    else:
        blocks.append(_section("No decision records in this PR."))
    conflicts = [f for f in findings if f.kind == "conflict"]
    if conflicts:
        lines = ["*:rotating_light: Conflicts with existing decisions*"]
        lines += [f"• {f.record_id} · {f.file}: {f.message}" for f in conflicts]
        blocks.append(_section("\n".join(lines)))
    return {"text": title, "blocks": blocks}


def deploy_payload(report: DeployReport, project: str, repo_url: str) -> dict:
    title = f"Dev deployment #{report.run_number or report.sha[:7]}"
    context = [t for t in (f"{project} · {report.env}" if project else report.env, _repo_link(repo_url)) if t]
    blocks: list[dict] = [_header(title), _context(*context)]
    if report.prs:
        lines = []
        for p in report.prs:
            label = f"PR #{p['number']} · {p['title']}"
            lines.append(f"<{p['url']}|{label}>" if p.get("url") else label)
        blocks.append(_section("\n".join(lines)))
    for r in report.records:
        lines = [f"Linked context: {r.id} {r.title}"]
        watch = r.section("Watch out")
        if watch:
            lines.append(f"Known consideration: {watch}")
        blocks.append(_section("\n".join(lines)))
    if not report.prs and not report.records:
        blocks.append(_section("No pull requests or decision records in this deployment."))
    return {"text": title, "blocks": blocks}


def post_webhook(url: str | None, payload: dict, opener: Callable = urllib.request.urlopen) -> bool:
    """POST `payload` as JSON to a Slack incoming webhook. Never raises; returns True on success."""
    if not url:
        print("Slack not configured — skipped")
        return False
    try:
        request = urllib.request.Request(
            url, data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json"},
        )
        response = opener(request, timeout=_TIMEOUT_SECONDS)
        close = getattr(response, "close", None)
        if callable(close):
            close()
        return True
    except urllib.error.HTTPError as e:
        reason = f"HTTP {e.code}"
    except Exception as e:  # noqa: BLE001 - Slack must never fail a command
        # Never print str(e): urllib and http.client embed the secret webhook URL in messages.
        reason = type(e).__name__
    print(f"Slack post failed: {reason}", file=sys.stderr)
    return False
