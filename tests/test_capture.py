from datetime import date

import pytest

from changetrace.capture import CaptureError, capture, guards_from_diff, observe, scan_secrets, supersede
from changetrace.records import Guard, load_records
from helpers import CTX001_DRAFT, dev_a_ships_ctx001, set_retry, write


def test_capture_from_diff_fills_guard(scenario):
    a = scenario.dev_a
    set_retry(a, "0")
    rec = capture(a, CTX001_DRAFT, from_diff=True, today=date(2026, 11, 18))
    assert rec.id == "CTX-001" and rec.author == "DevA" and rec.status == "active"
    assert rec.created == "2026-11-18"
    assert rec.guards == [Guard("worker/config.py", "RETRY_DELAY_SECONDS", "0", "2")]
    assert "worker/config.py#RETRY_DELAY_SECONDS" in rec.touches
    assert rec.path.name == "CTX-001-immediate-retry-for-failed-jobs.md"
    assert rec.path.read_bytes().count(b"\r") == 0
    assert load_records(a)[0].guards == rec.guards


def test_guards_from_diff_skips_context_dir(scenario):
    a = scenario.dev_a
    set_retry(a, "0")
    capture(a, CTX001_DRAFT, from_diff=True)
    assert guards_from_diff(a) == [Guard("worker/config.py", "RETRY_DELAY_SECONDS", "0", "2")]


def test_capture_dedups_touches(scenario):
    a = scenario.dev_a
    set_retry(a, "0")
    draft = CTX001_DRAFT.replace("---\n\n", "touches:\n  - worker/config.py#RETRY_DELAY_SECONDS\n---\n\n", 1)
    rec = capture(a, draft, from_diff=True)
    assert rec.touches.count("worker/config.py#RETRY_DELAY_SECONDS") == 1


def test_capture_refuses_secret(scenario):
    with pytest.raises(CaptureError, match=r"possible secret \(line \d+: credential-assignment\)") as exc:
        capture(scenario.dev_a, CTX001_DRAFT + "\napi_key = abcdef123456\n")
    assert "abcdef123456" not in str(exc.value)
    assert load_records(scenario.dev_a) == []


def test_capture_requires_decided(scenario):
    with pytest.raises(CaptureError):
        capture(scenario.dev_a, "---\ntitle: X\n---\n\n## Watch out\nY\n")


def test_capture_requires_title(scenario):
    with pytest.raises(CaptureError):
        capture(scenario.dev_a, "---\ntags: [a]\n---\n\n## Decided\nY\n")


def test_capture_proposed_status(scenario):
    rec = capture(scenario.dev_a, "---\ntitle: X\nstatus: proposed\n---\n\n## Decided\nY\n")
    assert rec.status == "proposed"


def test_scan_secrets_patterns():
    assert scan_secrets("key AKIAABCDEFGHIJKLMNOP here") == [(1, "aws-access-key")]
    assert scan_secrets("ghp_" + "a" * 24)
    assert scan_secrets("-----BEGIN RSA PRIVATE KEY-----")
    assert scan_secrets("https://hooks.slack.com/services/T0/B0/xyz")
    assert scan_secrets("ok\nPassword: hunter22") == [(2, "credential-assignment")]
    assert scan_secrets("plain prose about tokens") == []


def test_supersede_marks_old(scenario):
    dev_a_ships_ctx001(scenario)
    new = supersede(scenario.dev_b, "CTX-001", "---\ntitle: Controlled backoff\n---\n\n## Decided\nBackoff.\n")
    old = {r.id: r for r in load_records(scenario.dev_b)}["CTX-001"]
    assert new.id == "CTX-002" and new.supersedes == ["CTX-001"]
    assert old.status == "superseded" and old.superseded_by == "CTX-002"
    assert old.title == "Immediate retry for failed jobs" and old.guards[0].expect == "0"


def test_supersede_requires_active(scenario):
    dev_a_ships_ctx001(scenario)
    supersede(scenario.dev_b, "CTX-001", "---\ntitle: B\n---\n\n## Decided\nB.\n")
    with pytest.raises(CaptureError):
        supersede(scenario.dev_b, "CTX-001", "---\ntitle: C\n---\n\n## Decided\nC.\n")
    with pytest.raises(CaptureError):
        supersede(scenario.dev_b, "CTX-999", "---\ntitle: C\n---\n\n## Decided\nC.\n")


def test_observe(scenario):
    rec = observe(scenario.dev_a, ["CTX-001"], "dev", "86", "---\ntitle: Request burst\n---\n\n## What happened\nBurst.\n")
    assert rec.id == "OBS-001" and rec.about == ["CTX-001"] and rec.deployment == "86"
    assert rec.kind == "observation" and rec.environment == "dev" and rec.status == "active"


def test_capture_from_diff_refuses_secret_guard(scenario):
    a = scenario.dev_a
    write(a, "worker/secrets.py", 'API_KEY = "abcdef123456"\n')
    with pytest.raises(CaptureError):
        capture(a, CTX001_DRAFT, from_diff=True)
    assert load_records(a) == []


def test_supersede_from_diff_refuses_secret_guard(scenario):
    dev_a_ships_ctx001(scenario)
    b = scenario.dev_b
    write(b, "worker/secrets.py", 'API_KEY = "abcdef123456"\n')
    with pytest.raises(CaptureError):
        supersede(b, "CTX-001", "---\ntitle: Backoff\n---\n\n## Decided\nB.\n", from_diff=True)
    recs = load_records(b)
    assert [r.id for r in recs] == ["CTX-001"] and recs[0].status == "active"
