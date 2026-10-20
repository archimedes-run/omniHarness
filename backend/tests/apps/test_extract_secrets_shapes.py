"""extract_secrets lifts the shapes it used to miss (#59 review, plan §6).

Probed against the old code with synthetic values: URL credentials, bearer
tokens and short passwords were left in the text, and ``Tr0ub4dor&3x`` was
lifted only up to ``&``, leaving ``&3x`` in the prompt. Every value here is
synthetic.
"""

from __future__ import annotations

import pytest

from app.gateway.mcp_build_flow import extract_secrets

LIFTED = [
    # (text, the secret value, the name it is stored under)
    ("fetch https://alice:s3cr3tpw@api.example.com/v1", "s3cr3tpw", "API_EXAMPLE_COM_PASSWORD"),
    ("db is postgres://bob:pa55@db.internal:5432/x", "pa55", "DB_INTERNAL_PASSWORD"),
    ("send header Authorization: Bearer abc123.def", "abc123.def", "BEARER_TOKEN"),
    ("use Basic dXNlcjpwYXNz for it", "dXNlcjpwYXNz", "BASIC_AUTH"),
    ("my password is hunter2", "hunter2", "PASSWORD"),
    ("use pwd=letmein", "letmein", "PASSWORD"),
    ("password: Tr0ub4dor&3x", "Tr0ub4dor&3x", "PASSWORD"),
    ("my password is hunter2.", "hunter2", "PASSWORD"),
    ("the pin is 4821", "4821", "PIN"),
    ("x-api-key: 12345678", "12345678", "API_KEY"),
    ("token is ghp_short1", "ghp_short1", "TOKEN"),
]


@pytest.mark.parametrize(("text", "value", "name"), LIFTED, ids=[t for t, _, _ in LIFTED])
def test_each_shape_is_lifted_whole(text: str, value: str, name: str) -> None:
    out = extract_secrets(text)
    assert out.secrets.get(name) == value, out
    assert value not in out.text
    # Nothing of the value is left behind: no tail after the placeholder.
    placeholder = "{{secret:" + name + "}}"
    assert placeholder in out.text
    tail = out.text.split(placeholder, 1)[1]
    assert not any(tail.startswith(value[i:]) for i in range(1, len(value)) if len(value[i:]) >= 2), out.text


KEPT = [
    "the token is required for every call",
    "a password field on the form",
    "the password is required",
    "use the Bearer scheme",
    "visit https://api.example.com/v1/items",
]


@pytest.mark.parametrize("text", KEPT)
def test_ordinary_words_are_not_lifted(text: str) -> None:
    out = extract_secrets(text)
    assert out.secrets == {}, out
    assert out.text == text
