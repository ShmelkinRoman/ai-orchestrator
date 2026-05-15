import logging
import os
import shutil
import subprocess
from pathlib import Path
from config.settings import QWEN_API_BASE, OPENROUTER_API_KEY
from agents.llm import pick_developer  # S4: unified in agents/llm

logger = logging.getLogger(__name__)

AIDER_CMD = shutil.which("aider") or str(Path.home() / ".local/bin/aider")

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"

# Aider invocation profile per developer alias.
_DEVELOPER_PROFILES = {
    "qwen-local": {
        "aider_model": "openai/qwen",
        "api_base": QWEN_API_BASE,
        "extra_flags": ["--no-verify-ssl", "--no-show-model-warnings",
                        "--edit-format", "whole", "--map-tokens", "0"],
        "env": {"OPENAI_API_KEY": "none"},
    },
    "claude-sonnet-4-6": {
        "aider_model": "openrouter/anthropic/claude-sonnet-4.6",
        "api_base": _OPENROUTER_BASE,
        "extra_flags": ["--map-tokens", "0", "--edit-format", "diff"],
        "env": {"OPENAI_API_KEY": OPENROUTER_API_KEY, "OPENROUTER_API_KEY": OPENROUTER_API_KEY},
    },
    # deepseek-coder removed from OpenRouter; deepseek-chat is the current coding model
    "deepseek-coder": {
        "aider_model": "openrouter/deepseek/deepseek-chat",
        "api_base": _OPENROUTER_BASE,
        "extra_flags": ["--map-tokens", "0", "--edit-format", "diff"],
        "env": {"OPENAI_API_KEY": OPENROUTER_API_KEY, "OPENROUTER_API_KEY": OPENROUTER_API_KEY},
    },
}



def _profile(model_alias: str) -> dict:
    if model_alias not in _DEVELOPER_PROFILES:
        raise ValueError(f"Unknown developer model alias: {model_alias}")
    return _DEVELOPER_PROFILES[model_alias]


def run(repo_path: str, prompt: str, allowed_files: list[str] | None = None,
        model_alias: str = "qwen-local") -> dict:
    """Runs aider with the chosen developer model, returns {success, diff, changed_files}."""
    profile = _profile(model_alias)

    cmd = [
        AIDER_CMD,
        "--model", profile["aider_model"],
        "--openai-api-base", profile["api_base"],
        "--no-auto-commits",
        "--yes",
        *profile["extra_flags"],
        "--message", prompt,
    ]
    if allowed_files:
        cmd.extend(allowed_files)

    env = os.environ.copy()
    env.update(profile.get("env") or {})

    logger.info("Running aider in %s with model alias '%s'", repo_path, model_alias)
    try:
        result = subprocess.run(
            cmd,
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=600,
            env=env,
        )
        stdout = result.stdout
        stderr = result.stderr
        success = result.returncode == 0
    except subprocess.TimeoutExpired:
        logger.error("Aider timed out after 600s in %s", repo_path)
        return {"success": False, "diff": "", "changed_files": [],
                "stdout": "", "stderr": "Aider timed out after 600s"}

    if not success:
        logger.warning("Aider exited %d\nSTDERR: %s", result.returncode, stderr[:500])

    # get diff
    diff_result = subprocess.run(
        ["git", "diff", "HEAD"],
        cwd=repo_path, capture_output=True, text=True
    )
    diff = diff_result.stdout

    # get changed files (modified + new untracked)
    files_result = subprocess.run(
        ["git", "status", "--porcelain"],
        cwd=repo_path, capture_output=True, text=True
    )
    changed = [
        line[3:].strip()
        for line in files_result.stdout.splitlines()
        if line.strip() and not line.startswith("??")  # exclude untracked outside project
    ]
    # also include untracked new files (created by aider)
    untracked = [
        line[3:].strip()
        for line in files_result.stdout.splitlines()
        if line.startswith("??")
    ]
    changed = list(dict.fromkeys(changed + untracked))  # deduplicate, preserve order

    return {"success": success, "diff": diff, "changed_files": changed,
            "stdout": stdout, "stderr": stderr}


def commit_changes(repo_path: str, message: str):
    subprocess.run(["git", "add", "-A"], cwd=repo_path, check=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo_path, check=True)


def run_tests(repo_path: str) -> dict:
    """Runs lint, typecheck, pytest. Returns {passed, output}."""
    output_parts = []
    passed = True

    for cmd, label in [
        (["python3", "-m", "flake8", "--max-line-length=120", "--ignore=E501,W503,E241", "."], "flake8"),
        (["python3", "-m", "pytest", "--tb=short", "-q"], "pytest"),
    ]:
        r = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, timeout=120)
        out = r.stdout + r.stderr
        output_parts.append(f"=== {label} (exit {r.returncode}) ===\n{out[:1000]}")
        if r.returncode != 0:
            passed = False

    return {"passed": passed, "output": "\n".join(output_parts)}
