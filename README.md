# AI-SDLC Orchestrator

Automated AI-driven software development lifecycle pipeline.

## Features
- Takes GitHub Issues with `ai-ready` label
- Normalizes tasks (Intake agent → Qwen)
- Risk triage (auto-classification)
- Technical spec generation (Claude Sonnet)
- Code generation via Aider + Qwen
- Automated testing with retry
- AI code review (model selected by risk)
- Pull Request creation
- Human approval via Telegram inline buttons
- Automated docs update after merge

## Setup
1. Copy `.env.example` to `.env` and fill credentials
2. Install: `pip install litellm PyGithub python-telegram-bot python-dotenv pyyaml`
3. Run: `python3 main.py`

## Pipeline
```
Backlog → Triage → Needs Clarification → Technical Spec → Ready for Dev
→ In Development → Tests Running → AI Review → Human Approval
→ Ready to Merge → Released → Docs Updated
```
