from __future__ import annotations

import json

from click.testing import CliRunner

from changetrace.cli import main
from changetrace.gitops import git
from changetrace.records import parse_record
from helpers import (
    CTX001_DRAFT, CTX001_RECORD, dev_a_ships_ctx001, finish_and_merge, set_retry, write,
)

OBS_DRAFT = "---\ntitle: Retry burst seen on dev\n---\n\n## Observed\nBurst of retries.\n"


def test_acceptance_dev_a_to_dev_b(scenario):
    r = CliRunner()
    set_retry(scenario.dev_a, "0")
    out = r.invoke(main, ["capture", "--from-diff", "--repo", str(scenario.dev_a)], input=CTX001_DRAFT)
    assert out.exit_code == 0 and "Saved CTX-001" in out.output
    finish_and_merge(scenario)
    set_retry(scenario.dev_b, "2")
    res = r.invoke(main, ["check", "--repo", str(scenario.dev_b)])
    assert res.exit_code == 1
    assert "CTX-001" in res.output and "Watch out:" in res.output and "moved away from" in res.output
    why_out = r.invoke(main, ["why", "RETRY_DELAY_SECONDS", "--repo", str(scenario.dev_b)])
    assert "Immediate retry for failed jobs" in why_out.output


def test_check_json_and_markdown(scenario):
    dev_a_ships_ctx001(scenario)
    set_retry(scenario.dev_b, "2")
    j = CliRunner().invoke(main, ["check", "--format", "json", "--repo", str(scenario.dev_b)])
    assert json.loads(j.output)[0]["kind"] == "conflict"
    m = CliRunner().invoke(main, ["check", "--format", "markdown", "--repo", str(scenario.dev_b)])
    assert m.exit_code == 1 and "### ChangeTrace" in m.output and "CTX-001" in m.output


def test_check_clean_exits_zero(scenario):
    dev_a_ships_ctx001(scenario)
    res = CliRunner().invoke(main, ["check", "--repo", str(scenario.dev_b)])
    assert res.exit_code == 0 and "no conflicts" in res.output


def test_validate_exit_code(scenario):
    dev_a_ships_ctx001(scenario)
    assert CliRunner().invoke(main, ["validate", "--repo", str(scenario.dev_b)]).exit_code == 0
    write(scenario.dev_b, ".context/decisions/CTX-009-bad.md", "not a record")
    res = CliRunner().invoke(main, ["validate", "--repo", str(scenario.dev_b)])
    assert res.exit_code == 1 and "CTX-009-bad.md" in res.output


def test_capture_from_input_file(scenario, tmp_path):
    draft = tmp_path / "draft.md"
    draft.write_text(CTX001_DRAFT, encoding="utf-8")
    res = CliRunner().invoke(main, ["capture", "--input", str(draft), "--repo", str(scenario.dev_a)])
    assert res.exit_code == 0 and "Saved CTX-001 → .context/decisions/CTX-001-" in res.output


def test_capture_secret_refused(scenario):
    res = CliRunner().invoke(
        main, ["capture", "--repo", str(scenario.dev_a)],
        input=CTX001_DRAFT + "\nkey AKIAABCDEFGHIJKLMNOP\n")
    assert res.exit_code == 1 and "error:" in res.output


def test_supersede_and_observe(scenario):
    dev_a_ships_ctx001(scenario)
    a = str(scenario.dev_a)
    r = CliRunner()
    res = r.invoke(main, ["supersede", "CTX-001", "--repo", a], input=CTX001_DRAFT)
    assert res.exit_code == 0 and "Saved CTX-002" in res.output
    obs = r.invoke(main, ["observe", "--about", "CTX-002", "--env", "dev", "--deployment", "7",
                          "--repo", a], input=OBS_DRAFT)
    assert obs.exit_code == 0 and "Saved OBS-001 → .context/observations/OBS-001-" in obs.output


def test_explain_and_history(scenario):
    dev_a_ships_ctx001(scenario)
    b = str(scenario.dev_b)
    ex = CliRunner().invoke(main, ["explain", "worker/config.py", "--repo", b])
    assert ex.exit_code == 0 and "CTX-001" in ex.output
    h = CliRunner().invoke(main, ["history", "--key", "RETRY_DELAY_SECONDS", "--repo", b])
    assert h.exit_code == 0 and "CTX-001" in h.output and "2 → 0" in h.output


def test_corrupt_record_is_clean_error(scenario):
    write(scenario.dev_b, ".context/decisions/CTX-001-bad.md", "garbage")
    res = CliRunner().invoke(main, ["why", "X", "--repo", str(scenario.dev_b)])
    assert res.exit_code == 1 and "error:" in res.output
    assert "Traceback" not in res.output


def test_renumber(scenario):
    dev_a_ships_ctx001(scenario)
    b = scenario.dev_b
    git(b, "checkout", "-b", "x")
    write(b, ".context/decisions/CTX-001-other.md",
          CTX001_RECORD.replace("Immediate retry for failed jobs", "Other"))
    res = CliRunner().invoke(main, ["renumber", "--repo", str(b)])
    assert res.exit_code == 0 and "Renumbered CTX-001 → CTX-002" in res.output
    assert parse_record((b / ".context/decisions/CTX-002-other.md").read_text(encoding="utf-8")).id == "CTX-002"
    assert not (b / ".context/decisions/CTX-001-other.md").exists()
    assert len(list((b / ".context/decisions").glob("CTX-001-*.md"))) == 1  # base record untouched


def test_renumber_fixes_branch_references(scenario):
    dev_a_ships_ctx001(scenario)
    b = scenario.dev_b
    git(b, "checkout", "-b", "x")
    write(b, ".context/decisions/CTX-001-other.md",
          CTX001_RECORD.replace("Immediate retry for failed jobs", "Other"))
    ref = (CTX001_RECORD.replace("CTX-001", "CTX-005").replace("Immediate retry for failed jobs", "Next")
           .replace("supersedes: []", "supersedes: [CTX-001]"))
    write(b, ".context/decisions/CTX-005-next.md", ref)
    res = CliRunner().invoke(main, ["renumber", "--repo", str(b)])
    assert res.exit_code == 0
    nxt = parse_record((b / ".context/decisions/CTX-005-next.md").read_text(encoding="utf-8"))
    assert nxt.supersedes == ["CTX-006"]
    assert (b / ".context/decisions/CTX-006-other.md").exists()


def test_renumber_noop(scenario):
    dev_a_ships_ctx001(scenario)
    res = CliRunner().invoke(main, ["renumber", "--repo", str(scenario.dev_b)])
    assert res.exit_code == 0 and "Renumbered" not in res.output
