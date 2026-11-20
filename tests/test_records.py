from pathlib import Path

import pytest

from changetrace.records import (
    Guard,
    RecordError,
    next_id,
    parse_record,
    record_path,
    render_record,
)

SAMPLE = """---
id: CTX-001
kind: decision
title: Immediate retry for failed jobs
status: active
author: Dev A
created: 2026-11-18
touches: [worker/config.py#RETRY_DELAY_SECONDS]
guards:
  - {file: worker/config.py, key: RETRY_DELAY_SECONDS, expect: "0", previous: "2"}
supersedes: []
superseded_by: null
tags: [worker, retry]
---

## Decided
Default retry delay is 0.

## Watch out
Restoring 2 reintroduces slow recovery.
"""


def test_parse_roundtrip():
    r = parse_record(SAMPLE)
    assert r.id == "CTX-001" and r.guards[0] == Guard("worker/config.py", "RETRY_DELAY_SECONDS", "0", "2")
    assert r.section("Watch out") == "Restoring 2 reintroduces slow recovery."
    assert parse_record(render_record(r)) == r


def test_parse_accepts_crlf_and_bom():
    r = parse_record("\ufeff" + SAMPLE.replace("\n", "\r\n"))
    assert r.title == "Immediate retry for failed jobs" and r.section("Decided") == "Default retry delay is 0."


def test_guard_values_are_strings():
    r = parse_record(SAMPLE.replace('expect: "0"', "expect: 0"))
    assert r.guards[0].expect == "0"


def test_bad_status_raises():
    with pytest.raises(RecordError):
        parse_record(SAMPLE.replace("status: active", "status: maybe"))


def test_next_id_and_path(tmp_path):
    d = tmp_path / ".context/decisions"
    d.mkdir(parents=True)
    (d / "CTX-001-a.md").write_text(SAMPLE, encoding="utf-8")
    (d / "CTX-007-b.md").write_text(SAMPLE.replace("CTX-001", "CTX-007"), encoding="utf-8")
    assert next_id(tmp_path, "decision") == "CTX-008"
    assert next_id(tmp_path, "observation") == "OBS-001"
    r = parse_record(SAMPLE)
    assert record_path(tmp_path, r) == d / "CTX-001-immediate-retry-for-failed-jobs.md"


def test_load_records_wraps_non_utf8(tmp_path):
    from changetrace.records import load_records
    d = tmp_path / ".context/decisions"
    d.mkdir(parents=True)
    (d / "CTX-001-bad.md").write_bytes(b"---\ntitle: \xff\xfe\n---\n")
    with pytest.raises(RecordError, match=r"CTX-001-bad\.md: not valid UTF-8"):
        load_records(tmp_path)


def test_guard_with_null_expect_is_rejected():
    for bad in ("expect: null", "expect:"):
        with pytest.raises(RecordError):
            parse_record(SAMPLE.replace('expect: "0"', bad))


def test_slugify_falls_back_when_no_ascii_alphanumerics():
    from changetrace.records import slugify
    assert slugify("再試行") == "record"



def _with_path(raw: str, touches: bool = False) -> str:
    q = '"' + raw.replace("\\", "\\\\") + '"'
    text = SAMPLE.replace("file: worker/config.py", f"file: {q}")
    if touches:
        q2 = '"' + raw.replace("\\", "\\\\") + '#RETRY_DELAY_SECONDS"'
        text = text.replace("touches: [worker/config.py#RETRY_DELAY_SECONDS]", f"touches: [{q2}]")
    return text


@pytest.mark.parametrize("raw", ["./worker/config.py", r"worker\config.py", "worker//./config.py",
                                 "worker/x/../config.py", r".\worker\config.py"])
def test_guard_and_touch_paths_are_normalised(raw):
    r = parse_record(_with_path(raw, touches=True))
    assert r.guards[0].file == "worker/config.py"
    assert r.touches == ["worker/config.py#RETRY_DELAY_SECONDS"]


@pytest.mark.parametrize("raw", ["../x.py", "worker/../../x.py", "/etc/x.py", "C:/x.py", r"..\x.py"])
def test_guard_path_outside_repo_is_an_error(raw):
    with pytest.raises(RecordError):
        parse_record(_with_path(raw))
