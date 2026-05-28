# How others are evaluating finance LLM skills, and what is relevant here

A pass through the recent literature and tooling on how researchers and
practitioners are grading or benchmarking finance LLM agents and skills,
with notes on what maps to this project and what does not.

## 1. Direct benchmarks for finance LLM agents

### Anthropic's Real-World Finance evaluation (internal benchmark)

Anthropic's Claude 4.6 system card includes a "Real-World Finance" eval
that comprises around 50 difficult tasks drawn from real analyst
workflows, grouped across four verticals (investment banking, private
equity, hedge funds and public investing, and corporate finance). About
80 percent of the tasks are spreadsheet deliverables. Tasks are graded
primarily through rubric-based evaluation, with code execution and tool-
use agentic harnesses inside the scoring loop. Source: [Claude Opus 4.6
System Card](https://www-cdn.anthropic.com/0dd865075ad3132672ee0ab40b05a53f14cf5288.pdf).
Maps directly to what this project is doing for the same kinds of
deliverables (tearsheet, comps, capital-allocation are all spreadsheet
tasks in the same analyst-workflow space).

### Anthropic's Skill-creator evaluation system (recent)

Anthropic upgraded the skill-creator with an evaluation system that
gives direct feedback on whether a skill functions as intended after
execution, plus benchmarking on pass rate, execution time, and token
usage. Sources: [Anthropic Skill-Creator Upgrade](https://www.toolmesh.ai/news/anthropic-skill-creator-major-upgrade-evaluation),
[Tessl: Anthropic brings evals to skill-creator](https://tessl.io/blog/anthropic-brings-evals-to-skill-creator-heres-why-thats-a-big-deal/),
[Skill Creator 2.0](https://www.thetoolnerd.com/p/anthropic-skill-creator-20-update),
[anthropics/skills/skill-creator/SKILL.md](https://github.com/anthropics/skills/blob/main/skills/skill-creator/SKILL.md).
The pass-rate / execution-time / token-usage triad maps onto the
existing scorecard's accuracy / latency / cost columns. The "is this
skill functioning as intended" signal is closer to the behavioral
conformance layer the second worker pointed at than to the numerical
correctness layer.

### Finance Agent Benchmark (already cited)

[arXiv 2508.00828](https://arxiv.org/abs/2508.00828) measures real
finance research tasks across a range of LLM agents. Anchors used in
this project's `settings.yaml`: o3 at $3.78 per query and 3.1 minutes
per task with 46.8 percent accuracy, versus a human analyst at $25.66
and 16.8 minutes. The 46.8 percent number is the load-bearing data
point for the "LLMs hallucinate finance numbers" principle.

### WorkstreamBench (new since the original spec)

[arXiv 2605.22664](https://arxiv.org/abs/2605.22664) evaluates LLM
agents on end-to-end spreadsheet tasks in finance, with a three-
dimensional evaluation taxonomy covering Accuracy, Formula, and Format
along fine-grained criteria. Closely aligned with what this project
produces. The "Formula" dimension is essentially the FMP-self-check
derived-cell leg (does the formula the agent applied match the inputs
that were available). The "Format" dimension is essentially the
workflow-completion layer the second worker is pointing at.

### FinanceBench, FinQA, ConvFinQA, TAT-QA

A family of benchmarks with different scoring rules: FinanceBench is
percent correct, FinQA and ConvFinQA use exact match, TAT-QA uses F1.
This project's tolerance-band approach is more liberal than exact match
and more structured than percent correct. The SAB 99 grounding is
specifically for the FLAG / WARN boundary, which most of these
benchmarks do not encode at all.

### BizFinBench

[arXiv 2505.19457](https://arxiv.org/pdf/2505.19457) is a business-
driven financial benchmark for evaluating LLMs on real-world business
finance scenarios. More applied than the academic benchmarks above.

### FinanceReasoning

A 238-question subset focused on the most challenging financial
reasoning tasks, with chained multi-step quantitative reasoning. The
Claude family leads the leaderboard and produces the most professional-
looking outputs, but every model degrades sharply once a calculation
chains beyond a few steps. Source: [Awesome Agents Finance LLM
Leaderboard 2026](https://awesomeagents.ai/leaderboards/finance-llm-leaderboard/).
Notable observation from this leaderboard's commentary: the Claude Web
agent commits an off-by-one error when aggregating across multiple
periods, which is the same failure pattern this project's verifier
caught on JPM's `shares_outstanding` (summed across four quarters,
which is the multi-period aggregation failure mode at scale).

### SkillsBench

[arXiv 2602.12670](https://arxiv.org/html/2602.12670v1) measures the
efficacy of "Skills augmentation" in LLM-based agents specifically.
Methodological innovation: every task is run under both vanilla (no
skills) and skills-augmented conditions, with the comparison being the
measurement. Maps directly onto the project's M6 A/B framing (variant A
with Daloopa skill versus variant B with FMP skill), and would
generalize cleanly to a "vanilla agent versus skill-equipped agent"
comparison if added later.

## 2. Agent-trace and tool-call evaluation (the second worker's layer)

### LLM Output Drift for financial workflows

[arXiv 2511.07585](https://arxiv.org/pdf/2511.07585) on cross-provider
validation and mitigation of LLM output drift in financial workflows.
Directly relevant to the behavioral conformance layer. The framing
treats drift as a first-class failure mode rather than a side effect.

### OpenTelemetry-style traces plus LLM judges

The dominant pattern in production agent evaluation tooling (Arize AX
and Phoenix OSS, MLflow Agent Platform, Datadog LLM Observability,
Langfuse) is to capture distributed traces via OpenTelemetry spans and
then run LLM judges on either single spans or the entire trace.
Sources: [Arize: LLM-as-a-Judge primer](https://arize.com/llm-as-a-judge/),
[MLflow Agent Platform](https://mlflow.org/llm-as-a-judge),
[Datadog custom LLM judges](https://docs.datadoghq.com/llm_observability/evaluations/custom_llm_as_a_judge_evaluations/),
[Langfuse LLM-as-a-Judge](https://langfuse.com/docs/evaluation/evaluation-methods/llm-as-a-judge),
[Vinod Rane: Agent Evaluation for LLMs](https://medium.com/@vinodkrane/chapter-8-agent-evaluation-for-llms-how-to-test-tools-trajectories-and-llm-as-judge-788f6f3e0d52).
Two scopes used in practice:

- Span scope: input and output of one LLM call, agent step, or tool
  invocation in isolation. Useful for per-step accuracy.
- Trace scope: every span of a trace fed to the LLM judge in one
  prompt, so the evaluation can reason across steps. Useful for
  detecting redundant tool calls or unnecessary reasoning loops.

The `ToolCallEfficiency` metric specifically identifies redundant tool
calls and unnecessary reasoning loops. This is the off-path detection
layer that the second worker was describing, with concrete prior art on
how to implement it.

### Calibrating LLM-as-judge

[LangChain: Calibrate LLM-as-a-Judge with Human Corrections](https://www.langchain.com/articles/llm-as-a-judge)
documents the practical method: collect human corrections to the LLM
judge's verdicts, then either fine-tune the judge or fold the
corrections into the prompt as anchors. The same pattern fits this
project's FLAG-override feedback hook in `optimize/feedback.py`.

### IteraJudge

A novel LLM evaluation method designed to reduce bias when LLMs serve
as evaluators on objective metrics. Relevant to keeping the behavioral
conformance layer honest (an LLM judge of an LLM analyst is gameable in
exactly the way an LLM grader of LLM arithmetic is, and IteraJudge is
one named response to that).

### LLM observability tools

[LangChain: 8 LLM Observability Tools](https://www.langchain.com/articles/llm-observability-tools)
summarizes the current tooling landscape. Useful as a reference for
which production-grade trace infrastructure the behavioral conformance
layer should plug into.

## 3. Production-grade benchmarking tools

- [JurisTech: Best LLM Tools for Financial Analysis 2026 (hallucination benchmark)](https://juristech.net/best-llm-tools-for-financial-analysis-2026/)
- [aimultiple: Benchmark of 38 LLMs in Finance](https://aimultiple.com/finance-llm)

The aimultiple benchmark reports a logarithmic cost-accuracy
relationship with Claude 3.7 Sonnet on the efficiency frontier. This
maps onto the `cost_per_run_warn` reference in `settings.yaml` and
suggests that a cost-vs-accuracy efficient-frontier plot would be a
defensible scorecard add.

## 4. Net read on where this project sits

This project sits firmly on the "numerical correctness for analyst
spreadsheets" axis. It is closest in spirit to WorkstreamBench's
Accuracy and Formula dimensions, with a more liberal banded tolerance
schema grounded in SEC SAB 99 rather than exact match. The neuro-
symbolic split is unusual in the related work: most public benchmarks
use either exact-match heuristics or LLM-as-judge, while this project
splits the LLM's semantic work from Python's arithmetic, which avoids
the "LLM grading LLM" failure mode the FAITH and Finance Agent
Benchmark papers warn about.

The second worker's behavioral conformance framing is well-supported by
the related work. Production-grade trace evaluation (OpenTelemetry plus
LLM judges) and finance-specific drift research (arXiv 2511.07585) both
treat process drift as a first-class problem. The architecture in this
project already captures every tool call via stream-json and already
pins SKILL.md as a protected ground truth, so wiring trace-scope LLM
judges on top of the existing scorecard is the natural next milestone.

The Anthropic skill-creator evaluation system upgrade is worth
tracking, because if its built-in pass-rate / execution-time / token-
usage signals become the standard, this project's `metrics.py` should
align field names to match for interoperability.
