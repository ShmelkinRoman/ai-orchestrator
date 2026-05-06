# AI-SDLC Orchestrator

## Overview
Orchestrates GitHub Issues through a full AI-driven development pipeline:
Issues → Intake → Triage → Architect → Aider/Qwen → Tests → Review → PR → Human Approval → Docs

## Run
```bash
cd ~/ai-orchestrator
python3 main.py
```

## Key Files
- `main.py` — pipeline orchestrator
- `config/settings.py` — all settings from .env
- `config/models.yaml` — model routing
- `agents/` — pipeline stage agents
- `runner/aider_runner.py` — Aider + Qwen runner
- `github/client.py` — GitHub API
- `github/project.py` — GitHub Projects V2 kanban
- `notifications/telegram.py` — Telegram bot

## Environment
Copy `.env.example` to `.env` and fill in credentials.

## Architecture
- LiteLLM routes qwen-local → http://100.110.246.46/v1
- OpenRouter for Claude (architect, high-risk reviewer)
- Telegram bot handles human approval via inline buttons
