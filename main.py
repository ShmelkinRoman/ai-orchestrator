"""AI-SDLC Orchestrator — main entry point."""
import asyncio
import logging
import os
import re
import subprocess
import tempfile
from pathlib import Path

import agents.architect as architect_agent
import agents.context as context_agent
import agents.docs as docs_agent
import agents.intake as intake_agent
import agents.llm as llm
import agents.reviewer as reviewer_agent
import agents.triage as triage_agent
import gh_client.client as gh
import gh_client.project as project
import notifications.telegram as tg
import runner.aider_runner as aider
from config.settings import GITHUB_REPO, GITHUB_TOKEN

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("orchestrator")

CLONE_BASE = Path(tempfile.gettempdir()) / "ai-orch-repos"


def _clone_repo(issue_number: int) -> Path:
    import shutil
    CLONE_BASE.mkdir(parents=True, exist_ok=True)
    target = CLONE_BASE / f"repo-{issue_number}"
    url = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
    if target.exists():
        try:
            subprocess.run(["git", "checkout", "main"], cwd=str(target),
                           check=True, capture_output=True)
            subprocess.run(["git", "pull", "origin", "main"], cwd=str(target),
                           check=True, capture_output=True)
            return target
        except subprocess.CalledProcessError:
            logger.warning("repo-%d: stale clone, re-cloning", issue_number)
            shutil.rmtree(target)
    subprocess.run(["git", "clone", url, str(target)], check=True)
    return target


def _slugify(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text[:40].strip("-")


def _extract_keywords(intake_result: dict) -> list[str]:
    story = intake_result.get("user_story", "")
    title = intake_result.get("title", "")
    words = re.findall(r"\b[a-zA-Z]{4,}\b", title + " " + story)
    stop = {"want", "that", "with", "this", "from", "have", "will", "user", "should", "able"}
    return list({w.lower() for w in words if w.lower() not in stop})[:8]


async def process_issue(issue) -> None:
    num = issue.number
    title_raw = issue.title
    body = issue.body or ""
    node_id = issue.raw_data.get("node_id", "")

    logger.info("=== Processing issue #%d: %s ===", num, title_raw)
    llm.reset_run_costs()
    stages: dict[str, str] = {}

    # --- Step 1: Intake ---
    await tg.send_task_started(num, title_raw)
    tg.update_task_status(num, title_raw, "Intake")
    project.move_issue(num, node_id, "Triage")

    intake = intake_agent.run(f"Title: {title_raw}\n\n{body}")
    title = intake.get("title", title_raw)

    # --- Step 2: Triage ---
    triage = triage_agent.run(intake)
    risk = triage["risk"]

    gh.remove_label(issue, "ai-ready")
    gh.add_label(issue, "ai-in-progress")
    gh.add_label(issue, f"risk-{risk}")

    if triage["needs_clarification"]:
        project.move_issue(num, node_id, "Needs Clarification")
        questions = "\n".join(f"- {q}" for q in triage["clarification_questions"])
        gh.add_comment(issue, f"❓ **Нужны уточнения:**\n{questions}")
        tg.update_task_status(num, title, "Needs Clarification")
        stages["spec"] = "needs clarification"
        await tg.send_task_summary(num, title, stages, llm.get_run_cost_report(),
                                   error=f"Нужны уточнения:\n{questions}")
        return

    project.move_issue(num, node_id, "Technical Spec")

    # --- Step 3: Context ---
    repo_path = _clone_repo(num)
    keywords = _extract_keywords(intake)
    ctx = context_agent.gather(str(repo_path), keywords)

    # --- Step 4: Architect ---
    spec = architect_agent.run(intake, triage, ctx)
    qwen_prompt = architect_agent.extract_qwen_prompt(spec)
    gh.add_comment(issue, f"## 🏗️ Technical Spec\n\n{spec}")

    # --- Step 4b: Spec Approval ---
    project.move_issue(num, node_id, "Awaiting Spec Approval")
    tg.update_task_status(num, title, "Awaiting Spec Approval")

    spec_clarified = False
    for _attempt in range(2):
        spec_action, clarification = await tg.send_spec_approval_request(title, risk, spec, num)
        if spec_action == "approve":
            stages["spec"] = "approved" if not spec_clarified else "clarified→approved"
            break
        if spec_action == "cancel":
            project.move_issue(num, node_id, "Backlog")
            gh.remove_label(issue, "ai-in-progress")
            gh.add_label(issue, "ai-ready")
            tg.update_task_status(num, title, "Cancelled")
            stages["spec"] = "cancelled"
            await tg.send_task_summary(num, title, stages, llm.get_run_cost_report())
            return
        spec_clarified = True
        clarified_intake = {
            **intake,
            "user_story": intake.get("user_story", "") + f"\n\nClarification: {clarification}",
        }
        spec = architect_agent.run(clarified_intake, triage, ctx)
        qwen_prompt = architect_agent.extract_qwen_prompt(spec)
        gh.add_comment(issue, f"## 🏗️ Обновлённый Technical Spec\n\n{spec}")

    project.move_issue(num, node_id, "Ready for Dev")

    # --- Step 5: Aider + Qwen ---
    branch = f"ai/{num}-{_slugify(title)}"
    try:
        gh.create_branch(branch)
    except Exception as e:
        logger.warning("Branch create: %s", e)

    subprocess.run(["git", "fetch", "origin"], cwd=str(repo_path))
    subprocess.run(["git", "checkout", "-b", branch, f"origin/{branch}"],
                   cwd=str(repo_path), capture_output=True)

    project.move_issue(num, node_id, "In Development")
    tg.update_task_status(num, title, "In Development")

    aider_result = aider.run(str(repo_path), qwen_prompt or spec)

    if aider_result["changed_files"]:
        aider.commit_changes(str(repo_path), f"feat: {title} #{num}")

    diff = aider_result["diff"]
    changed_files = aider_result["changed_files"]
    stages["code"] = f"Qwen local ({len(changed_files)} files)"

    # --- Step 6: Tests ---
    project.move_issue(num, node_id, "Tests Running")
    tg.update_task_status(num, title, "Tests Running")

    test_result = aider.run_tests(str(repo_path))
    fix_attempts = 0
    while not test_result["passed"] and fix_attempts < 2:
        fix_attempts += 1
        fix_prompt = f"Fix test failures:\n{test_result['output'][:2000]}"
        aider.run(str(repo_path), fix_prompt, changed_files)
        aider.commit_changes(str(repo_path), f"fix: test fixes attempt {fix_attempts} #{num}")
        test_result = aider.run_tests(str(repo_path))

    if not test_result["passed"]:
        project.move_issue(num, node_id, "Needs Clarification")
        tg.update_task_status(num, title, "Tests Failed")
        stages["tests"] = "failed"
        await tg.send_task_summary(num, title, stages, llm.get_run_cost_report(),
                                   error=test_result["output"][:500])
        return

    stages["tests"] = "passed" if fix_attempts == 0 else f"passed ({fix_attempts} fix)"

    # --- Step 7: Review ---
    review = reviewer_agent.run(
        risk=risk,
        issue_body=f"Title: {title_raw}\n{body}",
        spec=spec,
        diff=diff,
        changed_files=changed_files,
        test_output=test_result["output"],
    )

    review_attempts = 0
    while review["verdict"] == "REQUEST_CHANGES" and review_attempts < 2:
        review_attempts += 1
        instructions = "\n".join(f"- {i}" for i in review["instructions_for_qwen"])
        fix_result = aider.run(str(repo_path), f"Fix code review issues:\n{instructions}")
        if fix_result["changed_files"]:
            aider.commit_changes(str(repo_path), f"fix: review fixes #{num}")
            diff = fix_result["diff"]
            changed_files = fix_result["changed_files"]
        review = reviewer_agent.run(
            risk=risk,
            issue_body=f"Title: {title_raw}\n{body}",
            spec=spec,
            diff=diff,
            changed_files=changed_files,
            test_output=test_result["output"],
        )

    stages["review"] = review["verdict"]
    project.move_issue(num, node_id, "AI Review")

    # --- Step 8: PR ---
    criteria_list = "\n".join(
        f"- [ ] {c}" for c in intake.get("acceptance_criteria", [])
    )
    pr_body = f"""## Summary
{spec.splitlines()[0] if spec else ''}

## Changes
{chr(10).join(f'- {f}' for f in changed_files)}

## Tests
```
{test_result['output'][:1000]}
```

## AI Review
{review['raw'][:500]}

## Acceptance Criteria
{criteria_list}

Closes #{num}
"""
    remote_url = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO}.git"
    subprocess.run(
        ["git", "push", "-f", remote_url, f"HEAD:{branch}"],
        cwd=str(repo_path), check=True
    )

    pr = gh.create_pull_request(
        title=f"feat(ai): {title} #{num}",
        body=pr_body,
        head=branch,
    )
    pr_url = pr.html_url

    project.move_issue(num, node_id, "Human Approval")
    tg.update_task_status(num, title, "Human Approval")

    # --- Step 9: Human Approval ---
    decision = await tg.send_approval_request(
        title, risk, len(changed_files), review["verdict"], pr_url, num
    )

    if decision == "merge":
        gh.merge_pull_request(pr.number)
        project.move_issue(num, node_id, "Released")
        gh.remove_label(issue, "ai-in-progress")
        gh.add_label(issue, "ai-done")
        tg.update_task_status(num, title, "Released")
        stages["merge"] = "merged"

        # --- Step 10: Docs ---
        subprocess.run(["git", "fetch", remote_url], cwd=str(repo_path))
        subprocess.run(["git", "checkout", "main"], cwd=str(repo_path), capture_output=True)
        reset_r = subprocess.run(
            ["git", "reset", "--hard", "FETCH_HEAD"],
            cwd=str(repo_path), capture_output=True,
        )
        if reset_r.returncode != 0:
            logger.warning("docs step: git reset --hard FETCH_HEAD failed, skipping docs push")
            stages["docs"] = "skipped"
        else:
            docs_agent.run(str(repo_path), changed_files, spec, diff)
            try:
                aider.commit_changes(str(repo_path), f"docs: update after #{num}")
                subprocess.run(["git", "push", remote_url, "main"], cwd=str(repo_path), check=True)
                stages["docs"] = "updated"
            except subprocess.CalledProcessError:
                stages["docs"] = "skipped"
        project.move_issue(num, node_id, "Docs Updated")
        tg.update_task_status(num, title, "Docs Updated")

    elif decision == "reject":
        gh.close_pull_request(pr.number)
        project.move_issue(num, node_id, "Backlog")
        gh.remove_label(issue, "ai-in-progress")
        gh.add_label(issue, "ai-ready")
        tg.update_task_status(num, title, "Rejected")
        stages["merge"] = "rejected"

    else:  # rework
        project.move_issue(num, node_id, "Needs Clarification")
        tg.update_task_status(num, title, "Needs Clarification")
        stages["merge"] = "rework"

    await tg.send_task_summary(num, title, stages, llm.get_run_cost_report())


async def main_loop():
    gh.ensure_labels()
    await tg.start_polling()

    try:
        issues = gh.get_ai_ready_issues()
        if not issues:
            logger.info("No ai-ready issues found.")
            await tg.send_message("🤖 Оркестратор запущен, нет задач с лейблом ai-ready.")
            return

        for issue in issues:
            try:
                await process_issue(issue)
            except Exception as e:
                logger.exception("Error processing issue #%d: %s", issue.number, e)
                await tg.send_message(f"💥 Ошибка при обработке #{issue.number}: {tg._safe_html(str(e)[:500])}")
    finally:
        await tg.stop_polling()


if __name__ == "__main__":
    asyncio.run(main_loop())
