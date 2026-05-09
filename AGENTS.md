# AGENTS.md — AI-SDLC Orchestrator

## What this project is

A Python pipeline that takes GitHub Issues and drives them through a full AI development cycle:
Issue → Intake → Triage → Architect → Spec Approval (human) → Aider+Qwen (code) → Tests → AI Review → PR → Human Approval → Docs

Entry point: `main.py`. Run with `python3 main.py`.

---

## File map

```
main.py                        — pipeline orchestrator, process_issue() function
config/
  settings.py                  — loads all env vars from .env; exports MODELS, GITHUB_REPO, etc.
  models.yaml                  — maps agent names to LLM aliases (qwen-local, openrouter/...)
  litellm.yaml                 — LiteLLM proxy config (not used at runtime, reference only)
agents/
  llm.py                       — complete(alias, messages) → str; cost tracking; model routing
  intake.py                    — run(issue_body) → dict with title/user_story/acceptance_criteria
  triage.py                    — run(intake) → {risk, needs_clarification, clarification_questions}
  architect.py                 — run(intake, triage, context) → spec string (markdown)
  reviewer.py                  — run(risk, issue_body, spec, diff, ...) → {verdict, instructions_for_qwen}
  docs.py                      — run(repo_path, changed_files, spec, diff) → updates docs in repo
  context.py                   — gather(repo_path, keywords) → {agents_md, file_snippets, ...}
runner/
  aider_runner.py              — run(repo_path, prompt) → {diff, changed_files}; run_tests() → {passed, output}
gh_client/
  client.py                    — GitHub API: issues, labels, branches, PRs, merge
  project.py                   — GitHub Projects V2 kanban: move_issue(num, node_id, column_name)
notifications/
  telegram.py                  — send_task_started(), send_spec_approval_request(), send_approval_request(), send_task_summary()
prompts/
  intake.md                    — system prompt for intake agent
  architect.md                 — system prompt for architect agent
  reviewer.md                  — system prompt for reviewer agent
  docs.md                      — system prompt for docs agent
tests/
  test_pipeline.py             — unit tests for agents (no network calls, no LLM)
```

---

## How to call the LLM

Always use `agents/llm.py`:

```python
from agents.llm import complete
from config.settings import MODELS

text = complete(MODELS["intake_agent"], messages, temperature=0.1, max_tokens=4096)
```

`MODELS` is a dict loaded from `config/models.yaml`. Current keys:
`intake_agent`, `triage_agent`, `context_agent`, `architect_agent`,
`reviewer_high`, `reviewer_medium`, `reviewer_low`, `docs_agent`

Never call `litellm.completion()` directly — cost tracking lives in `complete()`.

---

## How prompts work

Each agent loads its system prompt from `prompts/<name>.md` at import time:

```python
_PROMPT = (Path(__file__).parent.parent / "prompts/architect.md").read_text()
```

Then passes it as `{"role": "system", "content": _PROMPT}` in the messages list.

---

## How config works

All env vars are in `.env`. `config/settings.py` loads them with `python-dotenv`. Never hardcode values — always read from `settings.py`:

```python
from config.settings import GITHUB_REPO, GITHUB_TOKEN, MODELS
```

To add a new model alias: add a line to `config/models.yaml` and a price entry to `_COST_PER_1M` in `agents/llm.py`.

---

## Test runner

Tests live in `tests/`. Run with:

```bash
python3 -m pytest tests/ -v
python3 -m flake8 --max-line-length=120 --ignore=E501,W503 .
```

Tests must not make network calls, must not import `.env` values that aren't set, must not call `complete()`. Mock anything external. See `tests/test_pipeline.py` for existing patterns — new tests follow the same style.

---

## Key constraints

**Do not modify:**
- `.env` (secrets)
- `requirements.txt` (don't add dependencies without approval)
- `config/litellm.yaml` (reference config, not used at runtime)

**Safe to modify:**
- Any file in `agents/`, `runner/`, `gh_client/`, `notifications/`, `prompts/`, `tests/`
- `main.py`, `config/models.yaml`, `config/settings.py`

**Never do:**
- Call external APIs (GitHub, Telegram, LLM) in tests
- Use `print()` — use `logger = logging.getLogger(__name__)` everywhere
- Add a new agent without its model key in `config/models.yaml`
- Import from `notifications/telegram.py` inside agents — agents are pure functions

---

## Adding a new agent

1. Create `agents/<name>.py` with a `run(...)` function
2. Add `<name>_agent: <model-alias>` to `config/models.yaml`
3. Add a prompt file `prompts/<name>.md` if needed
4. Add unit tests in `tests/test_pipeline.py` that test parsing/logic without LLM calls
5. Wire into `main.py` → `process_issue()`

---

## Pipeline kanban columns (in order)

Backlog → Triage → Needs Clarification → Technical Spec → Awaiting Spec Approval →
Ready for Dev → In Development → Tests Running → AI Review → Human Approval →
Ready to Merge → Released → Docs Updated

`project.move_issue(num, node_id, "Column Name")` — exact string must match.

---

## Risk classification (triage.py)

- **high**: auth, authentication, payment, billing, migration, security, password, secret, token, db, database
- **medium**: api, endpoint, backend, service, query, route — or > 3 changed files
- **low**: everything else

Reviewer model is chosen by risk: high → Sonnet, medium → GPT-4o-mini, low → Qwen.
