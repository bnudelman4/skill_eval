"""Headless Claude Code subprocess wrapper (M3).

run_skill() invokes `claude -p ... --bare --output-format json` in an isolated
workdir, parses the JSON envelope for cost/turns, measures wall-clock latency,
locates the produced xlsx artifact, and detects whether the intended skill
actually triggered. Secrets come from the inherited environment; keys are never
logged or passed on the command line.

The actual subprocess call is injected (runner=) so unit tests run fully mocked;
the default executor shells out for real, gated by the caller.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

from pydantic import BaseModel


@dataclass
class ProcResult:
    stdout: str
    stderr: str
    returncode: int


Runner = Callable[[list[str], str, Optional[int]], ProcResult]


@dataclass
class Envelope:
    cost_usd: float
    num_turns: int
    is_error: bool
    duration_ms: Optional[int]


class SkillRun(BaseModel):
    skill: str
    ticker: str
    period: str
    data_source: str
    workdir: str
    artifact_path: Optional[str]
    cost_usd: float
    latency_s: float
    num_turns: int
    exit_ok: bool
    raw_log_path: str
    activation_observed: bool
    skill_selected: Optional[str]


def build_command(
    *,
    prompt: str,
    model: str,
    max_turns: int,
    allowed_tools: list[str],
    bare: bool,
    output_format: str,
) -> list[str]:
    cmd = ["claude", "-p", prompt, "--output-format", output_format]
    cmd += ["--model", model, "--max-turns", str(max_turns)]
    cmd += ["--allowedTools", ",".join(allowed_tools)]
    if bare:
        cmd.append("--bare")
    return cmd


def parse_envelope(stdout: str) -> Envelope:
    """Extract the result envelope. Tolerates leading log noise by scanning
    lines from the end for the last one that parses as the result object."""
    obj = None
    text = stdout.strip()
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        for line in reversed(text.splitlines()):
            line = line.strip()
            if not line:
                continue
            try:
                cand = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(cand, dict) and "total_cost_usd" in cand:
                obj = cand
                break
    if not isinstance(obj, dict):
        raise ValueError("no parseable result envelope found in stdout")
    return Envelope(
        cost_usd=float(obj.get("total_cost_usd", 0.0)),
        num_turns=int(obj.get("num_turns", 0)),
        is_error=bool(obj.get("is_error", False)),
        duration_ms=obj.get("duration_ms"),
    )


_SKILL_PATTERNS = [
    re.compile(r"[Uu]sing skill ['\"]?([a-z0-9_\-]+)['\"]?"),
    re.compile(r"Skill\(([a-z0-9_\-]+)\)"),
    re.compile(r"skill[: ]+['\"]([a-z0-9_\-]+)['\"]"),
]


def parse_activation(log: str, intended_skill: str) -> tuple[bool, Optional[str]]:
    """Best-effort: which skill triggered, and did the intended one trigger.

    activation_observed (intended triggered) and skill_selected (which one) are
    distinct metrics, kept separate on purpose.
    """
    selected: Optional[str] = None
    for pat in _SKILL_PATTERNS:
        m = pat.search(log)
        if m:
            selected = m.group(1)
            break
    return (selected == intended_skill, selected)


TIMEOUT_RETURNCODE = 124  # conventional timeout exit code


def _default_runner(cmd: list[str], cwd: str, timeout: Optional[int]) -> ProcResult:
    try:
        proc = subprocess.run(
            cmd, cwd=cwd, timeout=timeout, capture_output=True, text=True
        )
    except subprocess.TimeoutExpired as exc:
        # A slow run must not crash the batch: surface partial output + a marker
        # so run_skill records a failed SkillRun and the grid continues.
        out = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        err = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return ProcResult(out, f"{err}\nTIMEOUT after {timeout}s", TIMEOUT_RETURNCODE)
    return ProcResult(proc.stdout, proc.stderr, proc.returncode)


def _build_prompt(skill: str, ticker: str, period: str, data_source: str, out: str) -> str:
    return (
        f"Use the {skill} skill to produce the deliverable for {ticker} for "
        f"{period}, sourcing data from {data_source}. Save the resulting "
        f"spreadsheet to {out}. Do every numeric calculation yourself and write "
        f"the xlsx; do not ask follow-up questions."
    )


def run_skill(
    skill_name: str,
    ticker: str,
    period: str,
    data_source: str,
    *,
    workdir: Path,
    model: str,
    timeout: int,
    allowed_tools: Optional[list[str]] = None,
    bare: bool = True,
    output_format: str = "json",
    runner: Optional[Runner] = None,
    skill_src_dir: Optional[Path] = None,
) -> SkillRun:
    workdir = Path(workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    runner = runner or _default_runner
    tools = allowed_tools or ["Read", "Bash", "Write"]

    # Stage the skill into the isolated workdir so --bare (which skips ~/.claude
    # auto-discovery) can still load it. The skill dir name becomes its trigger.
    if skill_src_dir is not None:
        src = Path(skill_src_dir)
        dest = workdir / ".claude" / "skills" / src.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(src, dest)

    artifact = workdir / "output" / f"{skill_name}_{ticker}_{period}.xlsx"
    prompt = _build_prompt(skill_name, ticker, period, data_source, str(artifact))
    cmd = build_command(
        prompt=prompt, model=model, max_turns=25, allowed_tools=tools,
        bare=bare, output_format=output_format,
    )

    t0 = time.monotonic()
    proc = runner(cmd, str(workdir), timeout)
    latency_s = time.monotonic() - t0

    raw_log = workdir / "run.log"
    raw_log.write_text(
        f"$ {' '.join(cmd)}\n\n--- STDOUT ---\n{proc.stdout}\n--- STDERR ---\n{proc.stderr}",
        encoding="utf-8",
    )

    cost_usd, num_turns, env_error = 0.0, 0, True
    try:
        env = parse_envelope(proc.stdout)
        cost_usd, num_turns, env_error = env.cost_usd, env.num_turns, env.is_error
    except ValueError:
        pass  # envelope unparseable (e.g. crash before result) -> exit_ok False

    exit_ok = proc.returncode == 0 and not env_error
    observed, selected = parse_activation(proc.stdout + "\n" + proc.stderr, skill_name)

    return SkillRun(
        skill=skill_name,
        ticker=ticker,
        period=period,
        data_source=data_source,
        workdir=str(workdir),
        artifact_path=str(artifact) if (exit_ok and artifact.exists()) else None,
        cost_usd=cost_usd,
        latency_s=latency_s,
        num_turns=num_turns,
        exit_ok=exit_ok,
        raw_log_path=str(raw_log),
        activation_observed=observed,
        skill_selected=selected,
    )
