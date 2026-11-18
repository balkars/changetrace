import pytest

from changetrace.extractors import (
    Extracted,
    changed_keys,
    extract_value,
    normalize_value,
    read_keys,
    values_equal,
)

PY = 'import os\n\nRETRY_DELAY_SECONDS = int(os.getenv("RETRY_DELAY_SECONDS", 2))\nMAX_RETRIES = 5\nNAME = compute()\n'


@pytest.mark.parametrize("key,expected", [
    ("RETRY_DELAY_SECONDS", Extracted("found", "2")),
    ("MAX_RETRIES", Extracted("found", "5")),
    ("NAME", Extracted("unreadable")),
    ("ABSENT", Extracted("missing")),
])
def test_python(key, expected):
    assert extract_value("worker/config.py", PY, key) == expected


def test_python_crlf():
    assert extract_value("c.py", PY.replace("\n", "\r\n"), "MAX_RETRIES").value == "5"


def test_python_bom():
    assert extract_value("c.py", "\ufeff" + PY, "MAX_RETRIES").value == "5"


def test_environ_get_and_float():
    src = 'import os\nX = float(os.environ.get("X", 0.5))\n'
    assert extract_value("c.py", src, "X").value == "0.5"


def test_python_bare_getenv_annassign_and_last_wins():
    src = 'from os import getenv\nA: int = int(getenv("A", 3))\nB = 1\nB = 2\nC = True\n'
    assert extract_value("c.py", src, "A").value == "3"
    assert extract_value("c.py", src, "B").value == "2"
    assert extract_value("c.py", src, "C").value == "true"


def test_python_syntax_error_unreadable():
    assert extract_value("c.py", "def (:\n", "X") == Extracted("unreadable")


def test_python_ignores_nested_assignments():
    assert extract_value("c.py", "def f():\n    X = 1\n", "X") == Extracted("missing")


def test_yaml_json_toml_env_other():
    assert extract_value("s.yaml", "rate:\n  limit: 60\n", "rate.limit").value == "60"
    assert extract_value("s.yml", "rate:\n  limit: 60\n", "rate.limit").value == "60"
    assert extract_value("s.json", '{"rate": {"limit": 60}}', "rate.limit").value == "60"
    assert extract_value("s.toml", "[rate]\nlimit = 60\n", "rate.limit").value == "60"
    assert extract_value(".env", "RATE=60\n", "RATE").value == "60"
    assert extract_value(".env.local", "RATE='60'\n", "RATE").value == "60"
    assert extract_value("app.ini", "RATE = 60\n", "RATE").value == "60"


def test_structured_missing_and_unreadable():
    assert extract_value("s.yaml", "rate:\n  limit: 60\n", "rate.burst") == Extracted("missing")
    assert extract_value("s.yaml", "rate:\n  limit: 60\n", "rate") == Extracted("unreadable")
    assert extract_value("s.json", "{not json", "a") == Extracted("unreadable")
    assert extract_value("s.toml", "= bad", "a") == Extracted("unreadable")
    assert extract_value(".env", "A=1\n", "B") == Extracted("missing")
    assert extract_value("app.ini", "A = 1\n", "B") == Extracted("missing")


def test_crlf_in_structured_files():
    assert extract_value("s.yaml", "rate:\r\n  limit: 60\r\n", "rate.limit").value == "60"
    assert extract_value(".env", "RATE=60\r\n", "RATE").value == "60"
    assert extract_value("a.ini", "RATE = 60\r\n", "RATE").value == "60"


def test_normalize_value():
    assert normalize_value('  "abc" ') == "abc"
    assert normalize_value("'x'") == "x"
    assert normalize_value(True) == "true"
    assert normalize_value("False") == "false"
    assert normalize_value(60) == "60"


def test_values_equal_numeric():
    assert values_equal("0", "0.0") and values_equal('"0"', "0") and not values_equal("0", "2")
    assert values_equal("True", "true") and not values_equal("abc", "abd")


def test_read_keys():
    assert read_keys("c.py", PY) == {"RETRY_DELAY_SECONDS": "2", "MAX_RETRIES": "5"}
    assert read_keys("s.yaml", "a:\n  b: 1\n  c: [1, 2]\nd: x\n") == {"a.b": "1", "d": "x"}
    assert read_keys("s.json", '{"a": {"b": true}}') == {"a.b": "true"}
    assert read_keys("s.toml", "[a]\nb = 1\n") == {"a.b": "1"}
    assert read_keys(".env", "# c\nA=1\nexport B=\"two\"\n\n") == {"A": "1", "B": "two"}


def test_changed_keys():
    new = PY.replace('"RETRY_DELAY_SECONDS", 2', '"RETRY_DELAY_SECONDS", 0')
    assert changed_keys("worker/config.py", PY, new) == [("RETRY_DELAY_SECONDS", "2", "0")]


def test_changed_keys_new_file_and_added_key_sorted():
    assert changed_keys("c.py", None, "B = 2\nA = 1\n") == [("A", None, "1"), ("B", None, "2")]
    assert changed_keys("c.py", "A = 1\n", "A = 1\nB = 2\n") == [("B", None, "2")]
    assert changed_keys("c.py", "A = 1\n", "A = 1.0\n") == []  # formatting only
