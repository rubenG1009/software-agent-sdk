"""Tests for the verify-agent-server skill's control CLI and feature map.

The CLI lives at `.agents/skills/verify-agent-server/scripts/control_agent_server.py`.
These tests cover its pure helpers and validate the committed feature map's
structure (headings, IDs, index counts, and that every recipe command parses)
without launching a server.
"""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / ".agents/skills/verify-agent-server/scripts/control_agent_server.py"


def _load():
    spec = importlib.util.spec_from_file_location("control_agent_server", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["control_agent_server"] = module
    spec.loader.exec_module(module)
    return module


cas = _load()

ROUTES = [
    {"method": "GET", "path": "/api/conversations/{conversation_id}"},
    {"method": "GET", "path": "/api/conversations/search"},
    {"method": "POST", "path": "/api/conversations/{conversation_id}/pause"},
    {"method": "GET", "path": "/api/conversations/{conversation_id}/workspace/{file_path:path}"},
    {"method": "WS", "path": "/sockets/events/{conversation_id}"},
]


def test_template_matching_prefers_literal_routes():
    match = cas.match_route("GET", "/api/conversations/search", ROUTES)
    assert match["path"] == "/api/conversations/search"
    match = cas.match_route("GET", "/api/conversations/$CID", ROUTES)
    assert match["path"] == "/api/conversations/{conversation_id}"
    match = cas.match_route("GET", "/api/conversations/$CID/workspace/a/b.txt", ROUTES)
    assert match["path"].endswith("{file_path:path}")
    assert cas.match_route("DELETE", "/api/conversations/$CID", ROUTES) is None
    assert cas.match_route("WS", "/sockets/events/$CID", ROUTES)


@pytest.mark.parametrize(
    ("status", "expect", "ok"),
    [
        (200, None, True),
        (404, None, False),
        (201, "2xx", True),
        (422, "404,422", True),
        (401, "200", False),
    ],
)
def test_status_matches(status, expect, ok):
    assert cas.status_matches(status, expect) is ok


def test_dig_follows_dicts_and_lists():
    body = {"items": [{"id": "a"}, {"id": "b"}], "next": None}
    assert cas.dig(body, "items.1.id") == "b"
    assert cas.dig(body, "items.-1.id") == "b"
    assert cas.dig(body, "items.5.id") is None
    assert cas.dig(body, "missing") is None


def test_redactor_hides_known_secrets_and_cipher_tokens():
    redactor = cas.Redactor()
    redactor.add("super-secret-value", "session-api-key")
    token = "gAAAAA" + "x" * 60
    text = redactor.text(f"key=super-secret-value enc={token}")
    assert "super-secret-value" not in text
    assert token not in text
    assert "<redacted:session-api-key>" in text
    assert redactor.obj({"a": ["super-secret-value"]}) == {
        "a": ["<redacted:session-api-key>"]
    }


def test_extract_commands_handles_substitution_chains_and_fences():
    markdown = (
        "Run `CID=$(control-agent-server conversation start --prompt 'a (b)' "
        "--print-id)`, then `control-agent-server conversation wait \"$CID\" "
        "&& echo ok`.\n\n```sh\ncontrol-agent-server api GET /alive \\\n"
        "  --expect 200\n```\n"
    )
    commands = cas.extract_commands(markdown)
    assert commands == [
        "control-agent-server conversation start --prompt 'a (b)' --print-id",
        'control-agent-server conversation wait "$CID"',
        "control-agent-server api GET /alive    --expect 200",
    ]


def test_validate_command_uses_the_real_parser():
    assert cas.validate_command("control-agent-server api GET /alive --expect 200") is None
    assert cas.validate_command("control-agent-server ws stop live --expect-kind X") is None
    assert (
        cas.validate_command(
            "control-agent-server exec --save F00.x/y -- uv run python x.py --flag"
        )
        is None
    )
    error = cas.validate_command("control-agent-server api GET /alive --bogus")
    assert error and "--bogus" in error
    assert cas.validate_command("control-agent-server teleport") is not None


def test_extract_run_flag_anywhere():
    argv, run = cas.extract_run_flag(["api", "GET", "/alive", "--run", "/tmp/r"])
    assert argv == ["api", "GET", "/alive"]
    assert run == "/tmp/r"


def test_owned_routes_reads_wrapped_routes_paragraph(tmp_path):
    family = tmp_path / "F99-demo.md"
    family.write_text(
        "# Demo\n\nText.\n\nSource: `x`\n\nRoutes: `GET /alive`,\n"
        "`WS /sockets/events/{conversation_id}`\n\n## Sub-features\n"
    )
    assert [(m, p) for m, p, _ in cas.owned_routes(family)] == [
        ("GET", "/alive"),
        ("WS", "/sockets/events/{conversation_id}"),
    ]


def test_committed_feature_map_is_structurally_valid(capsys):
    """`map check --no-routes`: headings, IDs, index counts, recipes parse."""
    assert cas.main(["map", "check", "--no-routes"]) == 0, capsys.readouterr().out


def test_help_lists_examples_for_every_command(capsys):
    parser = cas.build_parser()
    for name in ("launch", "api", "doctor", "fixture", "exec", "restart", "stop"):
        with pytest.raises(SystemExit):
            parser.parse_args([name, "--help"])
        assert "Examples:" in capsys.readouterr().out, name


def test_usage_errors_are_one_json_object(capsys, tmp_path, monkeypatch):
    monkeypatch.setenv(cas.HOME_ENV, str(tmp_path))
    monkeypatch.delenv(cas.RUN_ENV, raising=False)
    code = cas.main(["api", "GET", "/alive"])
    payload = json.loads(capsys.readouterr().out)
    assert code == 3
    assert payload["ok"] is False
    assert "launch --new --print-run" in payload["hint"]
