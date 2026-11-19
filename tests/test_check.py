import json

import pytest

from changetrace.capture import supersede
from changetrace.check import (
    Finding, format_json, format_markdown, format_text, has_conflict, run_check,
)
from changetrace.gitops import git
from changetrace.records import load_records
from helpers import (
    CONFIG_PY, CTX001_RECORD, commit_all, dev_a_ships_ctx001, set_retry, write,
)

WORDINGS = [
    "Set default from 2 to 0 because the two-second wait delayed recovery.",
    "RETRY_DELAY_SECONDS must be 0, not 2.",
    "Keep RETRY_DELAY_SECONDS at 0.",
    "Changed RETRY_DELAY_SECONDS to 0 (was 2).",
    "Do not set it back to 2.",
]


@pytest.mark.parametrize("decided", WORDINGS)
def test_revert_conflicts_whatever_the_wording(scenario, decided):
    dev_a_ships_ctx001(scenario, decided)
    set_retry(scenario.dev_b, "2")
    f = run_check(scenario.dev_b)
    assert has_conflict(f)
    c = [x for x in f if x.kind == "conflict"][0]
    assert c.record_id == "CTX-001" and c.current == "2"
    assert "restores the value CTX-001 moved away from" in c.message


def test_committed_revert_still_conflicts(scenario):
    dev_a_ships_ctx001(scenario)
    b = scenario.dev_b
    git(b, "checkout", "-b", "r")
    set_retry(b, "2")
    commit_all(b, "revert")
    assert has_conflict(run_check(b))


def test_superseded_in_same_change_is_resolved(scenario):
    dev_a_ships_ctx001(scenario)
    b = scenario.dev_b
    set_retry(b, "2")
    supersede(b, "CTX-001", "---\ntitle: Controlled backoff\n---\n\n## Decided\nBackoff.\n")
    f = run_check(b)
    assert not has_conflict(f) and any(x.kind == "resolved" for x in f)


def test_removed_key_conflicts(scenario):
    dev_a_ships_ctx001(scenario)
    write(scenario.dev_b, "worker/config.py", "import os\n")
    assert run_check(scenario.dev_b)[0].message.startswith("guarded key removed")


def test_editing_merged_record_body_conflicts(scenario):
    dev_a_ships_ctx001(scenario)
    b = scenario.dev_b
    p = next((b / ".context/decisions").glob("CTX-001-*.md"))
    p.write_text(p.read_text(encoding="utf-8").replace("Default retry", "Some retry"), encoding="utf-8")
    assert any("append-only" in x.message for x in run_check(b))


def test_unrelated_change_no_findings(scenario):
    dev_a_ships_ctx001(scenario)
    write(scenario.dev_b, "README.md", "hi\n")
    assert run_check(scenario.dev_b) == []


def test_file_filter_and_markdown(scenario):
    dev_a_ships_ctx001(scenario)
    set_retry(scenario.dev_b, "2")
    f = run_check(scenario.dev_b, file="worker/config.py")
    md = format_markdown(f, {r.id: r for r in load_records(scenario.dev_b)})
    assert md.startswith("### ChangeTrace") and "1 conflict" in md
    assert "Decided" in md and "Watch out" in md


def test_check_without_origin(tmp_path):
    git(tmp_path, "init", "-b", "main")
    write(tmp_path, "worker/config.py", CONFIG_PY.replace(", 2)", ", 0)"))
    write(tmp_path, ".context/decisions/CTX-001-immediate-retry-for-failed-jobs.md", CTX001_RECORD)
    commit_all(tmp_path, "init")
    set_retry(tmp_path, "2")
    assert has_conflict(run_check(tmp_path))


def test_numeric_formatting_is_not_a_conflict(scenario):
    dev_a_ships_ctx001(scenario)
    set_retry(scenario.dev_b, "0.0")
    assert not has_conflict(run_check(scenario.dev_b))


def test_file_filter_excludes_other_files(scenario):
    dev_a_ships_ctx001(scenario)
    set_retry(scenario.dev_b, "2")
    assert run_check(scenario.dev_b, file="README.md") == []


def test_unguarded_touched_file_gives_info(scenario):
    dev_a_ships_ctx001(scenario)
    b = scenario.dev_b
    guards = 'guards:\n  - file: worker/config.py\n    key: RETRY_DELAY_SECONDS\n    expect: "0"\n    previous: "2"\n'
    rec2 = (CTX001_RECORD.replace("CTX-001", "CTX-002").replace("Immediate retry", "Queue notes")
            .replace("worker/config.py#RETRY_DELAY_SECONDS", "worker/queue.py")
            .replace(guards, "guards: []\n"))
    assert "guards: []" in rec2
    write(b, ".context/decisions/CTX-002-queue-notes-for-failed-jobs.md", rec2)
    commit_all(b, "add CTX-002")
    write(b, "worker/queue.py", "x = 1\n")
    f = [x for x in run_check(b) if x.record_id == "CTX-002"]
    assert [(x.kind, x.file, x.message) for x in f] == [
        ("info", "worker/queue.py", "relevant: CTX-002 Queue notes for failed jobs")]


def test_unreadable_guard_warns(scenario):
    dev_a_ships_ctx001(scenario)
    write(scenario.dev_b, "worker/config.py", "RETRY_DELAY_SECONDS = compute()\n")
    f = run_check(scenario.dev_b)
    assert [x.kind for x in f] == ["warning"] and "cannot verify — read CTX-001" in f[0].message
    assert not has_conflict(f)


def test_text_and_json_formats(scenario):
    dev_a_ships_ctx001(scenario)
    b = scenario.dev_b
    recs = {r.id: r for r in load_records(b)}
    assert format_text([], recs).strip().endswith("no conflicts")
    set_retry(b, "2")
    f = run_check(b)
    txt = format_text(f, recs)
    assert "✗ worker/config.py — changes RETRY_DELAY_SECONDS from 0 to 2" in txt
    assert "  CTX-001 · DevA · " in txt and ": Immediate retry for failed jobs" in txt
    assert "  Decided: Default retry delay is 0" in txt
    assert "  Watch out: Restoring 2" in txt
    assert txt.strip().endswith("1 conflict(s)")
    data = json.loads(format_json(f))
    assert data[0]["kind"] == "conflict" and data[0]["record_id"] == "CTX-001"
    assert isinstance(f[0], Finding)


def _ctx001_path(repo):
    return next((repo / ".context/decisions").glob("CTX-001-*.md"))


def test_deleted_record_conflicts(scenario):
    dev_a_ships_ctx001(scenario)
    b = scenario.dev_b
    _ctx001_path(b).unlink()
    set_retry(b, "2")
    f = run_check(b)
    assert has_conflict(f)
    assert any("append-only" in x.message for x in f)
    assert any(x.record_id == "CTX-001" and x.current == "2" for x in f)


def test_renamed_and_edited_record_conflicts(scenario):
    dev_a_ships_ctx001(scenario)
    b = scenario.dev_b
    p = _ctx001_path(b)
    text = p.read_text(encoding="utf-8").replace('expect: "0"', 'expect: "2"')
    p.unlink()
    write(b, ".context/decisions/CTX-001-renamed.md", text)
    set_retry(b, "2")
    f = run_check(b)
    assert has_conflict(f) and any("append-only" in x.message for x in f)


@pytest.mark.parametrize("status", ["proposed", "rejected"])
def test_status_downgrade_conflicts(scenario, status):
    dev_a_ships_ctx001(scenario)
    b = scenario.dev_b
    p = _ctx001_path(b)
    p.write_text(p.read_text(encoding="utf-8").replace("status: active", f"status: {status}"),
                 encoding="utf-8")
    set_retry(b, "2")
    f = run_check(b)
    assert any("changed from active" in x.message for x in f)
    assert any(x.kind == "conflict" and x.current == "2" for x in f)


def test_superseded_without_superseder_conflicts(scenario):
    dev_a_ships_ctx001(scenario)
    b = scenario.dev_b
    p = _ctx001_path(b)
    p.write_text(p.read_text(encoding="utf-8").replace("status: active", "status: superseded"),
                 encoding="utf-8")
    set_retry(b, "2")
    f = run_check(b)
    assert has_conflict(f) and not any(x.kind == "resolved" for x in f)


def test_staged_reads_the_index(scenario):
    dev_a_ships_ctx001(scenario)
    b = scenario.dev_b
    set_retry(b, "2")
    git(b, "add", "-A")
    set_retry(b, "0")
    assert has_conflict(run_check(b, staged=True))
    assert not has_conflict(run_check(b))


def test_relative_repo_path(scenario, monkeypatch):
    dev_a_ships_ctx001(scenario)
    set_retry(scenario.dev_b, "2")
    monkeypatch.chdir(scenario.dev_b.parent)
    assert has_conflict(run_check(scenario.dev_b.relative_to(scenario.dev_b.parent)))
