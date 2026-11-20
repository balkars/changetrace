from changetrace.validate import validate_repo
from helpers import dev_a_ships_ctx001, set_retry, write


def _msgs(repo):
    return [x.message for x in validate_repo(repo)]


def test_validate_clean(scenario):
    dev_a_ships_ctx001(scenario)
    assert validate_repo(scenario.dev_b) == []


def test_validate_duplicate_and_mismatch(scenario):
    dev_a_ships_ctx001(scenario); b = scenario.dev_b
    p = next(b.glob(".context/decisions/CTX-001-*.md"))
    (p.parent / "CTX-001-dup.md").write_text(p.read_text(encoding="utf-8"), encoding="utf-8")
    set_retry(b, "2")
    msgs = [x.message for x in validate_repo(b)]
    assert any("duplicate id CTX-001" in m for m in msgs) and any("expects 0, found 2" in m for m in msgs)


def test_validate_reports_bad_files_and_keeps_going(scenario):
    dev_a_ships_ctx001(scenario); b = scenario.dev_b
    d = b / ".context/decisions"
    (d / "CTX-005-bad.md").write_bytes(b"---\ntitle: \xff\n---\n")
    (d / "CTX-006-nofm.md").write_text("no front matter", encoding="utf-8")
    set_retry(b, "2")
    probs = validate_repo(b)
    msgs = [p.message for p in probs]
    assert "parse error: not valid UTF-8" in msgs and "parse error: missing front matter" in msgs
    assert any("expects 0, found 2" in m for m in msgs)
    assert {p.path for p in probs if p.message.startswith("parse error")} == {
        ".context/decisions/CTX-005-bad.md", ".context/decisions/CTX-006-nofm.md"}


def test_validate_missing_guard_and_links(scenario):
    dev_a_ships_ctx001(scenario); b = scenario.dev_b
    d = b / ".context/decisions"
    p = next(d.glob("CTX-001-*.md"))
    text = p.read_text(encoding="utf-8")
    p.write_text(text.replace("superseded_by: null", "superseded_by: CTX-002")
                 .replace("supersedes: []", "supersedes: [CTX-009]"), encoding="utf-8")
    write(b, "worker/config.py", "OTHER = 1\n")
    msgs = _msgs(b)
    assert "supersedes unknown CTX-009" in msgs
    assert "superseded_by CTX-002 does not supersede CTX-001" in msgs
    assert "guard RETRY_DELAY_SECONDS missing in worker/config.py" in msgs


def test_validate_possible_secret(scenario):
    dev_a_ships_ctx001(scenario); b = scenario.dev_b
    p = next((b / ".context/decisions").glob("CTX-001-*.md"))
    p.write_text(p.read_text(encoding="utf-8") + "\napi_key = abcdef123456\n", encoding="utf-8")
    msgs = _msgs(b)
    assert any(m.startswith("possible secret on line ") for m in msgs)
    assert "abcdef123456" not in "\n".join(msgs)


def test_validate_skill_copies_differ(scenario):
    b = scenario.dev_b
    write(b, ".agents/skills/changetrace/SKILL.md", "one\n")
    write(b, ".claude/skills/changetrace/SKILL.md", "one\n")
    assert _msgs(b) == []
    write(b, ".claude/skills/changetrace/SKILL.md", "two\n")
    assert "skill copies differ" in _msgs(b)
