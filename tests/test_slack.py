from __future__ import annotations

import io
import json
import urllib.error
from datetime import datetime

from click.testing import CliRunner

from changetrace.check import Finding
from changetrace.cli import main
from changetrace.deploy import DeployReport
from changetrace.github import GitHub
from changetrace.records import Record, parse_record
from changetrace.slack.notify import deploy_payload, post_webhook
from changetrace.slack.notify import pr_payload
from fakes import FakeGh
from helpers import CTX001_RECORD, commit_all, ctx001_draft, set_retry
from changetrace.gitops import git

WATCH = "Restoring 2 reintroduces slow recovery."
URL = "https://hooks.slack.test/services/T000/B000/SECRET"


def _record() -> Record:
    return parse_record(CTX001_RECORD)


def _pr(n=7):
    return {"number": n, "title": "Immediate retry", "url": f"https://x/pull/{n}", "author": "deva"}


def _text(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False)


def test_pr_payload_mentions_ctx_and_watch_out():
    p = pr_payload(_pr(), [_record()], [], "https://github.com/o/r", "Worker service")
    out = _text(p)
    assert p["text"] == "PR #7 · Immediate retry"
    assert p["blocks"][0] == {"type": "header", "text": {"type": "plain_text", "text": "PR #7 · Immediate retry"}}
    assert "deva · " in out
    assert "*CTX-001 · Immediate retry for failed jobs*" in out
    assert "Default retry delay is 0 (immediate retry)." in out
    assert ":warning: Watch out: Restoring 2 reintroduces slow recovery." in out
    assert "onflict" not in out


def test_pr_payload_lists_conflicts():
    f = Finding("conflict", "CTX-001", "worker/config.py", "RETRY_DELAY_SECONDS is 2, expected 0",
                "RETRY_DELAY_SECONDS", "2")
    out = _text(pr_payload(_pr(), [_record()], [f], ""))
    assert "Conflicts" in out and "CTX-001" in out and "expected 0" in out


def test_pr_payload_without_records_and_long_text_is_bounded():
    assert "No decision records" in _text(pr_payload(_pr(), [], [], ""))
    rec = _record()
    rec.body = "## Decided\n" + "x" * 5000 + "\n\n## Watch out\n" + "y" * 5000 + "\n"
    for b in pr_payload(_pr(), [rec], [], "")["blocks"]:
        if b["type"] == "section":
            assert len(b["text"]["text"]) <= 3000


def _report(run="42", prs=True):
    return DeployReport("dev", "a" * 40, run, None, ["c1"], [_pr(3)] if prs else [], [_record()], None)


def test_deploy_payload_lists_pr_and_ctx():
    p = deploy_payload(_report(), "Worker service", "https://github.com/o/r")
    out = _text(p)
    assert p["blocks"][0]["text"]["text"] == "Dev deployment #42"
    assert "PR #3 · Immediate retry" in out
    assert "Linked context: CTX-001 Immediate retry for failed jobs" in out
    assert f"Known consideration: {WATCH}" in out
    assert "Worker service" in out


def test_deploy_payload_header_falls_back_to_short_sha():
    p = deploy_payload(_report(run=None, prs=False), "Worker service", "")
    assert p["blocks"][0]["text"]["text"] == "Dev deployment #aaaaaaa"
    assert "PR #" not in _text(p)


class _Resp:
    status = 200

    def close(self):
        pass


def test_post_webhook_skips_without_url(capsys):
    calls = []
    for url in (None, ""):
        assert post_webhook(url, {"text": "x"}, opener=lambda *a, **k: calls.append(a)) is False
    assert calls == []
    assert capsys.readouterr().out.count("Slack not configured — skipped") == 2


def test_post_webhook_posts_json():
    seen = {}

    def opener(req, timeout=None):
        seen.update(body=req.data, ctype=req.get_header("Content-type"), url=req.full_url,
                    method=req.get_method(), timeout=timeout)
        return _Resp()

    payload = {"text": "héllo — ✓"}
    assert post_webhook(URL, payload, opener=opener) is True
    assert json.loads(seen["body"].decode("utf-8")) == payload
    assert seen["ctype"] == "application/json" and seen["method"] == "POST"
    assert seen["url"] == URL and seen["timeout"] == 10


def test_post_webhook_swallow_http_error(capsys):
    def opener(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, 404, "Not Found", {}, io.BytesIO(b""))

    assert post_webhook(URL, {"text": "x"}, opener=opener) is False
    err = capsys.readouterr().err
    assert "Slack post failed: HTTP 404" in err and "SECRET" not in err


def test_post_webhook_swallows_network_and_bad_url_errors(capsys):
    def boom(exc):
        def opener(req, timeout=None):
            raise exc
        return opener

    for exc in (urllib.error.URLError("dns down"), TimeoutError("timed out"), ConnectionResetError("reset")):
        assert post_webhook(URL, {}, opener=boom(exc)) is False
    assert post_webhook("not-a-url-SECRET", {}, opener=boom(ValueError("unknown url type: 'not-a-url-SECRET'"))) is False
    captured = capsys.readouterr()
    assert captured.err.count("Slack post failed:") == 4 and "SECRET" not in captured.err + captured.out
    # a malformed URL with the real opener must also be swallowed, offline
    assert post_webhook("not-a-url", {}) is False


def test_post_webhook_never_prints_secret_with_real_opener(capsys):
    for bad in ("https://h/a b" + chr(9) + "SECRET", "https://h:SECRETport/x", "https://h/a" + chr(10) + "SECRET",
                "SECRET-no-scheme"):
        assert post_webhook(bad, {"text": "x"}) is False
    captured = capsys.readouterr()
    assert "SECRET" not in captured.out + captured.err
    assert captured.err.count("Slack post failed:") == 4


# --- CLI -----------------------------------------------------------------

def _capture_webhook(monkeypatch, sink):
    def fake(url, payload, opener=None):
        sink.append((url, payload))
        return True
    monkeypatch.setattr("changetrace.cli.post_webhook", fake)


def _branch_with_ctx001(s):
    a = s.dev_a
    git(a, "checkout", "-b", "fix/immediate-retry")
    set_retry(a, "0")
    from changetrace.capture import capture
    capture(a, ctx001_draft(), from_diff=True)
    commit_all(a, "immediate retry")


def test_cli_notify_slack_pr_posts_records_from_branch(scenario, monkeypatch):
    _branch_with_ctx001(scenario)
    sink = []
    _capture_webhook(monkeypatch, sink)
    gh = GitHub("o/r", FakeGh({"api repos/o/r/pulls/5": {
        "number": 5, "title": "Immediate retry", "html_url": "https://x/pull/5", "user": {"login": "deva"}}}))
    monkeypatch.setattr("changetrace.cli._gh", lambda repo: gh)
    res = CliRunner().invoke(main, ["notify", "slack", "pr", "--pr", "5", "--repo", str(scenario.dev_a)],
                             env={"SLACK_WEBHOOK_URL": URL})
    assert res.exit_code == 0, res.output
    [(url, payload)] = sink
    assert url == URL
    out = _text(payload)
    assert "PR #5 · Immediate retry" in out and "CTX-001" in out and WATCH in out and "deva" in out


def test_cli_notify_slack_pr_without_gh_and_without_webhook(scenario, monkeypatch):
    _branch_with_ctx001(scenario)
    sink = []
    _capture_webhook(monkeypatch, sink)
    monkeypatch.setattr("changetrace.cli._gh", lambda repo: GitHub("o/r", FakeGh.offline()))
    res = CliRunner().invoke(main, ["notify", "slack", "pr", "--pr", "5", "--repo", str(scenario.dev_a)])
    assert res.exit_code == 0, res.output
    [(url, payload)] = sink
    assert url is None and "PR #5 · PR #5" in _text(payload) and "CTX-001" in _text(payload)


def test_cli_notify_slack_pr_not_configured_exits_zero(scenario, monkeypatch):
    _branch_with_ctx001(scenario)
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.setattr("changetrace.cli._gh", lambda repo: None)
    res = CliRunner().invoke(main, ["notify", "slack", "pr", "--pr", "5", "--repo", str(scenario.dev_a)])
    assert res.exit_code == 0 and "Slack not configured — skipped" in res.output


def test_cli_notify_slack_pr_ignores_records_not_in_branch(scenario, monkeypatch):
    from helpers import dev_a_ships_ctx001
    dev_a_ships_ctx001(scenario)  # CTX-001 already on main
    git(scenario.dev_a, "checkout", "-b", "docs-only")
    sink = []
    _capture_webhook(monkeypatch, sink)
    monkeypatch.setattr("changetrace.cli._gh", lambda repo: None)
    res = CliRunner().invoke(main, ["notify", "slack", "pr", "--pr", "6", "--repo", str(scenario.dev_a)])
    assert res.exit_code == 0, res.output
    assert "CTX-001" not in _text(sink[0][1]) and "No decision records" in _text(sink[0][1])


def test_cli_deploy_report_posts_to_slack(scenario, monkeypatch):
    from helpers import dev_a_ships_ctx001
    dev_a_ships_ctx001(scenario)
    sink = []
    _capture_webhook(monkeypatch, sink)
    monkeypatch.setattr("changetrace.cli._gh", lambda repo: None)
    head = git(scenario.dev_a, "rev-parse", "main")
    res = CliRunner().invoke(main, ["deploy", "report", "--sha", head, "--run-number", "9",
                                    "--repo", str(scenario.dev_a)], env={"SLACK_WEBHOOK_URL": URL})
    assert res.exit_code == 0, res.output
    [(url, payload)] = sink
    assert url == URL and "Dev deployment #9" in _text(payload) and f"Known consideration: {WATCH}" in _text(payload)
