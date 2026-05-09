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

    # --- Step 1: Intake ---
    tg.update_task_status(num, title_raw, "Intake")
    await tg.send_message(f"📋 Взято в работу: {title_raw} (#{num})")

    project.move_issue(num, node_id, "Triage")

    intake = intake_agent.run(f"Title: {title_raw}\n\n{body}")
    title = intake.get("title", title_raw)
    tg.update_task_status(num, title, "Intake done")

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
        await tg.send_message(f"❓ Нужны уточнения: {title} (#{num})\n{questions}")
        tg.update_task_status(num, title, "Needs Clarification")
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

    for _attempt in range(2):
        spec_action, clarification = await tg.send_spec_approval_request(title, risk, spec, num)
        if spec_action == "approve":
            break
        if spec_action == "cancel":
            project.move_issue(num, node_id, "Backlog")
            gh.remove_label(issue, "ai-in-progress")
            gh.add_label(issue, "ai-ready")
            await tg.send_message(f"❌ Задача отменена: {title} (#{num})")
            tg.update_task_status(num, title, "Cancelled")
            return
        # clarify: re-run architect with the clarification appended
        clarified_intake = {
            **intake,
            "user_story": intake.get("user_story", "") + f"\n\nClarification: {clarification}",
        }
        spec = architect_agent.run(clarified_intake, triage, ctx)
        qwen_prompt = architect_agent.extract_qwen_prompt(spec)
        gh.add_comment(issue, f"## 🏗️ Обновлённый Technical Spec\n\n{spec}")

    project.move_issue(num, node_id, "Ready for Dev")
    await tg.send_message(f"🏗️ Техспек одобрен: {title} (#{num})")

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
    await tg.send_message(f"💻 Qwen пишет код: {title} (#{num})")

    aider_result = aider.run(str(repo_path), qwen_prompt or spec)

    if aider_result["changed_files"]:
        aider.commit_changes(str(repo_path), f"feat: {title} #{num}")

    diff = aider_result["diff"]
    changed_files = aider_result["changed_files"]

    # --- Step 6: Tests ---
    project.move_issue(num, node_id, "Tests Running")
    tg.update_task_status(num, title, "Tests Running")

    test_result = aider.run_tests(str(repo_path))
    attempts = 0
    while not test_result["passed"] and attempts < 2:
        attempts += 1
        fix_prompt = f"Fix test failures:\n{test_result['output'][:2000]}"
        aider.run(str(repo_path), fix_prompt, changed_files)
        aider.commit_changes(str(repo_path), f"fix: test fixes attempt {attempts} #{num}")
        test_result = aider.run_tests(str(repo_path))

    if not test_result["passed"]:
        project.move_issue(num, node_id, "Needs Clarification")
        await tg.send_message(
            f"❌ Тесты упали: {title} (#{num})\n\n{test_result['output'][:500]}"
        )
        tg.update_task_status(num, title, "Tests Failed")
        return

    await tg.send_message(f"✅ Тесты прошли: {title} (#{num})")

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

    project.move_issue(num, node_id, "AI Review")
    await tg.send_message(
        f"👀 AI Review: {review['verdict']} — {title} (#{num})"
    )

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
    # push branch BEFORE creating PR (PR needs commits to exist on remote)
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

    approval_text = (
        f"🔀 PR готов: {title}\n"
        f"Risk: {risk} | Files: {len(changed_files)} | Tests: ✅ | AI Review: ✅ {review['verdict']}"
    )

    # --- Step 9: Human Approval ---
    decision = await tg.send_approval_request(approval_text, pr_url, num)

    if decision == "merge":
        gh.merge_pull_request(pr.number)
        project.move_issue(num, node_id, "Released")
        gh.remove_label(issue, "ai-in-progress")
        gh.add_label(issue, "ai-done")
        await tg.send_message(f"🚀 Смержено: {title} (#{num})")
        tg.update_task_status(num, title, "Released")

        # --- Step 10: Docs ---
        subprocess.run(["git", "fetch", remote_url], cwd=str(repo_path))
        subprocess.run(["git", "checkout", "main"], cwd=str(repo_path), capture_output=True)
        subprocess.run(["git", "pull", "--rebase", remote_url, "main"], cwd=str(repo_path))
        docs_agent.run(str(repo_path), changed_files, spec, diff)
        try:
            aider.commit_changes(str(repo_path), f"docs: update after #{num}")
            subprocess.run(["git", "push", remote_url, "main"], cwd=str(repo_path))
        except subprocess.CalledProcessError:
            pass  # skip if nothing to commit
        project.move_issue(num, node_id, "Docs Updated")
        await tg.send_message(f"📝 Документация обновлена: {title} (#{num})")
        tg.update_task_status(num, title, "Docs Updated")

    elif decision == "reject":
        gh.close_pull_request(pr.number)
        project.move_issue(num, node_id, "Backlog")
        gh.remove_label(issue, "ai-in-progress")
        gh.add_label(issue, "ai-ready")
        await tg.send_message(f"🚫 Отклонено: {title} (#{num})")
        tg.update_task_status(num, title, "Rejected")

    else:  # rework
        project.move_issue(num, node_id, "Needs Clarification")
        await tg.send_message(f"🔄 Отправлено на доработку: {title} (#{num})")
        tg.update_task_status(num, title, "Needs Clarification")


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
