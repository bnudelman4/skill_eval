"""M3: headless skill invocation. Unit tests mock the subprocess entirely.

The single live test (real `claude -p`) is skipped unless FINSKILL_ALLOW_LIVE
is set, so the suite never burns credits by default.
"""

import json
import os
from pathlib import Path

import pytest

from finskill_eval.runner.invoke_skill import (
    ProcResult,
    parse_activation,
    parse_envelope,
    run_skill,
)

SAMPLE_ENVELOPE = {
    "type": "result",
    "subtype": "success",
    "is_error": False,
    "num_turns": 7,
    "duration_ms": 42000,
    "result": "Done. Wrote output.",
    "total_cost_usd": 0.4213,
}


def test_build_command_uses_bare_and_allowed_tools():
    from finskill_eval.runner.invoke_skill import build_command

    cmd = build_command(
        prompt="hi", model="claude-sonnet-4-6", max_turns=25,
        allowed_tools=["Read", "Bash", "Write"], bare=True, output_format="json",
    )
    assert cmd[0] == "claude"
    assert "-p" in cmd and "hi" in cmd
    assert "--bare" in cmd
    assert "--output-format" in cmd and "json" in cmd
    assert "--max-turns" in cmd and "25" in cmd
    assert "--allowedTools" in cmd
    assert "Read,Bash,Write" in cmd
    assert "--model" in cmd and "claude-sonnet-4-6" in cmd


def test_build_command_omits_bare_when_false():
    from finskill_eval.runner.invoke_skill import build_command

    cmd = build_command(
        prompt="hi", model="m", max_turns=1, allowed_tools=["Read"],
        bare=False, output_format="json",
    )
    assert "--bare" not in cmd


def test_parse_envelope_extracts_fields():
    env = parse_envelope(json.dumps(SAMPLE_ENVELOPE))
    assert env.cost_usd == pytest.approx(0.4213)
    assert env.num_turns == 7
    assert env.is_error is False


def test_parse_envelope_finds_json_among_log_noise():
    noisy = "starting...\nsome log line\n" + json.dumps(SAMPLE_ENVELOPE) + "\n"
    env = parse_envelope(noisy)
    assert env.num_turns == 7


def test_parse_activation_detects_skill():
    log = "... Using skill 'tearsheet' to build the deliverable ..."
    observed, selected = parse_activation(log, "tearsheet")
    assert observed is True
    assert selected == "tearsheet"


def test_parse_activation_detects_wrong_skill_selected():
    log = "Skill(comps) invoked"
    observed, selected = parse_activation(log, "tearsheet")
    assert observed is False        # intended skill did not trigger
    assert selected == "comps"      # a different skill did


def test_parse_activation_none():
    observed, selected = parse_activation("no skills here", "tearsheet")
    assert observed is False
    assert selected is None


def test_run_skill_with_mocked_subprocess(tmp_path):
    workdir = tmp_path / "wd"
    workdir.mkdir()

    def fake_runner(cmd, cwd, timeout):
        # simulate the agent writing its artifact
        out = Path(cwd) / "output"
        out.mkdir(exist_ok=True)
        (out / "tearsheet_AAPL_FY2024.xlsx").write_bytes(b"PK\x03\x04stub")
        log = "Using skill 'tearsheet' ...\n" + json.dumps(SAMPLE_ENVELOPE)
        return ProcResult(stdout=log, stderr="", returncode=0)

    run = run_skill(
        "tearsheet", "AAPL", "FY2024", "fmp",
        workdir=workdir, model="claude-sonnet-4-6", timeout=600,
        runner=fake_runner,
    )
    assert run.exit_ok is True
    assert run.cost_usd == pytest.approx(0.4213)
    assert run.num_turns == 7
    assert run.latency_s >= 0.0
    assert run.artifact_path is not None and Path(run.artifact_path).exists()
    assert run.activation_observed is True
    assert run.skill_selected == "tearsheet"
    assert Path(run.raw_log_path).exists()


def test_run_skill_nonzero_exit_marks_not_ok(tmp_path):
    workdir = tmp_path / "wd"
    workdir.mkdir()

    def fake_runner(cmd, cwd, timeout):
        return ProcResult(stdout="", stderr="boom", returncode=1)

    run = run_skill(
        "comps", "AAPL", "FY2024", "fmp",
        workdir=workdir, model="m", timeout=10, runner=fake_runner,
    )
    assert run.exit_ok is False
    assert run.artifact_path is None
    assert Path(run.raw_log_path).exists()


@pytest.mark.skipif(
    not os.environ.get("FINSKILL_ALLOW_LIVE"),
    reason="live test; set FINSKILL_ALLOW_LIVE=1 to run (costs credits)",
)
def test_live_headless_envelope_is_parseable():
    """Real `claude -p` round-trip proves the subprocess path + envelope parse.

    Uses a trivial prompt (no skill) so it stays cheap; we only assert the
    harness can shell out and read a populated cost from the JSON envelope.
    """
    from dotenv import load_dotenv

    from finskill_eval.runner.invoke_skill import _default_runner, build_command

    # --bare forces the env ANTHROPIC_API_KEY (metered), bypassing any session
    # login. Verified: without --bare the CLI uses the local OAuth login instead.
    # Load .env so the metered key is present (pytest's env lacks it otherwise).
    load_dotenv(Path(".env"), override=True)
    assert os.environ.get("ANTHROPIC_API_KEY"), "ANTHROPIC_API_KEY missing from .env"
    cmd = build_command(
        prompt="say hi", model="claude-sonnet-4-6", max_turns=5,
        allowed_tools=["Read"], bare=True, output_format="json",
    )
    proc = _default_runner(cmd, ".", 120)
    # A populated cost on the metered key is the proof the call really ran;
    # we don't assert returncode because a trivial prompt may or may not consume
    # a tool turn.
    env = parse_envelope(proc.stdout)
    assert env.cost_usd > 0.0
    assert env.num_turns >= 1


def test_find_artifact_discovers_misplaced_xlsx(tmp_path):
    from finskill_eval.runner.invoke_skill import _find_artifact
    # skill saved to its own reports/ path, not the one we asked for
    (tmp_path / "reports").mkdir()
    f = tmp_path / "reports" / "AAPL_tearsheet.xlsx"
    f.write_bytes(b"PK\x03\x04")
    # staged skill file under .claude must be ignored
    (tmp_path / ".claude" / "skills").mkdir(parents=True)
    (tmp_path / ".claude" / "skills" / "x.xlsx").write_bytes(b"PK")
    found = _find_artifact(tmp_path)
    assert found == f


def test_run_skill_finds_misplaced_artifact(tmp_path):
    wd = tmp_path / "wd"
    def fake_runner(cmd, cwd, timeout, env=None):
        out = Path(cwd) / "reports"; out.mkdir(parents=True, exist_ok=True)
        (out / "AAPL_tearsheet.xlsx").write_bytes(b"PK\x03\x04")
        return ProcResult(json.dumps(SAMPLE_ENVELOPE), "", 0)
    run = run_skill("tearsheet","AAPL","FY2024","fmp", workdir=wd,
                    model="m", timeout=600, runner=fake_runner)
    assert run.artifact_path is not None and run.artifact_path.endswith("AAPL_tearsheet.xlsx")


def test_build_command_streamjson_adds_verbose():
    from finskill_eval.runner.invoke_skill import build_command
    cmd = build_command(prompt="x", model="m", max_turns=1,
                        allowed_tools=["Read"], bare=False, output_format="stream-json")
    assert "--verbose" in cmd


def test_parse_activation_from_streamjson_skill_path():
    # agent reading the staged skill is the activation signal
    log = '{"type":"assistant","message":{"content":[{"type":"tool_use","name":"Read","input":{"file_path":"/wd/.claude/skills/capital-allocation/SKILL.md"}}]}}'
    observed, selected = parse_activation(log, "capital_allocation")
    assert observed is True                      # hyphen/underscore-insensitive
    assert selected == "capital-allocation"
