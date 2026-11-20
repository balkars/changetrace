from changetrace.capture import supersede
from changetrace.github import GitHub
from changetrace.gitops import added_commit, git
from changetrace.query import explain, format_views, history, why
from fakes import FakeGh
from helpers import dev_a_ships_ctx001, write


def test_why_offline_still_prints(scenario):
    dev_a_ships_ctx001(scenario)
    v = why(scenario.dev_b, "RETRY_DELAY_SECONDS", GitHub("o/r", FakeGh.offline()))
    assert v[0].record.id == "CTX-001" and v[0].current
    assert "links unavailable" in format_views(v)


def test_why_without_gh_still_prints(scenario):
    dev_a_ships_ctx001(scenario)
    text = format_views(why(scenario.dev_b, "worker/config.py"))
    assert "CTX-001 · active · DevA" in text and "links unavailable (offline or gh not logged in)" in text
    assert "Decided: Default retry delay is 0" in text and "Watch out: Restoring 2" in text


def test_why_with_pr_and_deploy(scenario):
    dev_a_ships_ctx001(scenario); b = scenario.dev_b
    commit = added_commit(b, next(b.glob(".context/decisions/CTX-001-*.md")).relative_to(b).as_posix())
    head = git(b, "rev-parse", "HEAD")
    gh = FakeGh({f"api repos/o/r/commits/{commit}/pulls": [{"number": 1, "title": "Immediate retry", "html_url": "u", "user": {"login": "deva"}}],
                 "api repos/o/r/deployments?environment=dev": [{"id": 9, "sha": head, "created_at": "2026-11-18T14:20:00Z"}],
                 "api repos/o/r/deployments/9/statuses": [{"state": "success"}]})
    write(b, ".context/config.yml", "project: Worker service\ngithub: o/r\nenvironments: [dev]\n")
    text = format_views(why(b, "worker/config.py#RETRY_DELAY_SECONDS", GitHub("o/r", gh)))
    assert "PR #1" in text and f"dev deploy {head[:7]}" in text
    assert "links unavailable" not in text


def test_why_skips_deployments_that_predate_the_commit(scenario):
    dev_a_ships_ctx001(scenario); b = scenario.dev_b
    commit = added_commit(b, next(b.glob(".context/decisions/CTX-001-*.md")).relative_to(b).as_posix())
    old = git(b, "rev-parse", f"{commit}~1")
    gh = FakeGh({f"api repos/o/r/commits/{commit}/pulls": [],
                 "api repos/o/r/deployments?environment=dev": [
                     {"id": 8, "sha": "f" * 40, "created_at": "2026-11-17T10:00:00Z"},
                     {"id": 7, "sha": old, "created_at": "2026-11-17T09:00:00Z"}],
                 "api repos/o/r/deployments/8/statuses": [], "api repos/o/r/deployments/7/statuses": []})
    write(b, ".context/config.yml", "project: p\ngithub: o/r\nenvironments: [dev]\n")
    v = why(b, "RETRY_DELAY_SECONDS", GitHub("o/r", gh))
    assert v[0].evidence.deployments == [] and v[0].evidence.note is None


def test_why_follows_supersession(scenario):
    dev_a_ships_ctx001(scenario); b = scenario.dev_b
    supersede(b, "CTX-001", "---\ntitle: Controlled backoff\nguards: []\ntouches: [worker/config.py#RETRY_DELAY_SECONDS]\n---\n\n## Decided\nBackoff.\n")
    v = why(b, "RETRY_DELAY_SECONDS")
    assert [x.record.id for x in v] == ["CTX-002", "CTX-001"] and v[0].chain == ["CTX-001", "CTX-002"]
    assert [x.current for x in v] == [True, False]


def test_why_unknown_target_is_empty(scenario):
    dev_a_ships_ctx001(scenario)
    assert why(scenario.dev_b, "NOPE") == []
    assert format_views([]) == ""


def test_explain_matches_file(scenario):
    dev_a_ships_ctx001(scenario)
    assert [v.record.id for v in explain(scenario.dev_b, "worker/config.py")] == ["CTX-001"]
    assert explain(scenario.dev_b, "other.py") == []


def test_history_shows_value_changes(scenario):
    dev_a_ships_ctx001(scenario)
    texts = [h.text for h in history(scenario.dev_b, "RETRY_DELAY_SECONDS")]
    assert any("2 → 0" in t for t in texts) and any("CTX-001" in t for t in texts)
    assert any(t.startswith("RETRY_DELAY_SECONDS 2 → 0 (commit ") for t in texts)
    assert "CTX-001 Immediate retry for failed jobs (active)" in texts


def test_history_includes_deployment(scenario):
    dev_a_ships_ctx001(scenario); b = scenario.dev_b
    head = git(b, "rev-parse", "HEAD")
    gh = FakeGh({"api repos/o/r/deployments?environment=dev": [{"id": 9, "sha": head, "created_at": "2026-11-18T14:20:00Z"}],
                 "api repos/o/r/deployments/9/statuses": [{"state": "success"}]})
    write(b, ".context/config.yml", "project: p\ngithub: o/r\nenvironments: [dev]\n")
    h = history(b, "RETRY_DELAY_SECONDS", GitHub("o/r", gh))
    assert any(e.kind == "deployment" and e.text == f"dev deploy {head[:7]} (success)" for e in h)


def test_why_shows_replacement_that_does_not_mention_the_key(scenario):
    dev_a_ships_ctx001(scenario); b = scenario.dev_b
    supersede(b, "CTX-001", "---\ntitle: Controlled backoff\nguards: []\ntouches: [worker/config.py#RETRY_BACKOFF_MAX_SECONDS]\n---\n\n## Decided\nBackoff.\n")
    v = why(b, "RETRY_DELAY_SECONDS")
    assert [x.record.id for x in v] == ["CTX-002", "CTX-001"]
    assert v[0].current is True and v[1].current is False
    assert any("CTX-002" in e.text for e in history(b, "RETRY_DELAY_SECONDS"))
    assert [x.record.id for x in explain(b, "worker/config.py")][:2] == ["CTX-002", "CTX-001"]


def test_observations_are_evidence(scenario):
    from changetrace.capture import observe
    dev_a_ships_ctx001(scenario); b = scenario.dev_b
    observe(b, ["CTX-001"], "dev", "1", "---\ntitle: Request burst on dev\n---\n\n## Observed\nBurst.\n")
    views = why(b, "RETRY_DELAY_SECONDS")
    assert not any(v.record.kind == "observation" for v in views)
    assert "Observed: OBS-001 · dev · deployment 1 — Request burst on dev" in format_views(views)
    assert "OBS-001 Request burst on dev (observation about CTX-001)" in [e.text for e in history(b, "RETRY_DELAY_SECONDS")]


def test_why_matches_record_id(scenario):
    dev_a_ships_ctx001(scenario)
    assert [v.record.id for v in why(scenario.dev_b, "CTX-001")] == ["CTX-001"]


def test_why_record_id_follows_supersession(scenario):
    dev_a_ships_ctx001(scenario); b = scenario.dev_b
    supersede(b, "CTX-001", "---\ntitle: Controlled backoff\nguards: []\ntouches: [worker/config.py#RETRY_BACKOFF_MAX_SECONDS]\n---\n\n## Decided\nBackoff.\n")
    assert [v.record.id for v in why(b, "CTX-001")] == ["CTX-002", "CTX-001"]


def test_why_observation_id_shows_decision_it_is_about(scenario):
    from changetrace.capture import observe
    dev_a_ships_ctx001(scenario); b = scenario.dev_b
    observe(b, ["CTX-001"], "dev", "1", "---\ntitle: Request burst on dev\n---\n\n## Observed\nBurst.\n")
    views = why(b, "OBS-001")
    assert [v.record.id for v in views] == ["CTX-001"]
    assert "Observed: OBS-001" in format_views(views)


def test_why_unknown_record_id_is_empty(scenario):
    dev_a_ships_ctx001(scenario)
    assert why(scenario.dev_b, "CTX-999") == []
