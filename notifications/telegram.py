import asyncio
import logging

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_PROXY, GITHUB_REPO

logger = logging.getLogger(__name__)

_approval_queues: dict[str, asyncio.Queue] = {}
_app: Application | None = None
_active_tasks: dict[int, dict] = {}


def _normalize_proxy(proxy: str | None) -> str | None:
    if proxy and proxy.startswith("socks5h://"):
        return "socks5://" + proxy[len("socks5h://"):]
    return proxy


def _make_app() -> Application:
    builder = Application.builder().token(TELEGRAM_BOT_TOKEN)
    proxy = _normalize_proxy(TELEGRAM_PROXY)
    # Large pool: poller + pipeline sends run concurrently, default pool causes PoolTimeout
    request = HTTPXRequest(connection_pool_size=16, proxy=proxy)
    builder = builder.request(request)
    return builder.build()


def _safe_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def send_message(text: str):
    await _app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode="HTML")


def _issue_link(num: int, title: str) -> str:
    url = f"https://github.com/{GITHUB_REPO}/issues/{num}"
    return f'<a href="{url}">#{num} {_safe_html(title)}</a>'


async def send_task_started(num: int, title: str):
    await send_message(f"{_issue_link(num, title)} — начато")


async def send_task_summary(
    num: int,
    title: str,
    stages: dict[str, str],
    cost_report: dict,
    error: str | None = None,
):
    if error:
        icon = "🔴"
        status = "остановлено"
    elif stages.get("merge") in ("rejected", "rework"):
        icon = "🟡"
        status = stages["merge"]
    else:
        icon = "✅"
        status = "завершено"

    stage_order = ["spec", "code", "tests", "review", "merge", "docs"]
    result_lines = [
        f"  {k.capitalize()}: {stages[k]}"
        for k in stage_order if k in stages
    ]

    actual = cost_report.get("actual_usd", 0)
    sonnet = cost_report.get("sonnet_equivalent_usd", 0)
    saved = cost_report.get("saved_usd", 0)

    model_agg: dict[str, dict] = {}
    for row in cost_report.get("rows", []):
        m = row["model"]
        if m not in model_agg:
            model_agg[m] = {"cost": 0.0, "tokens": 0, "calls": 0}
        model_agg[m]["cost"] += row["cost_usd"]
        model_agg[m]["tokens"] += row["input_tokens"] + row["output_tokens"]
        model_agg[m]["calls"] += 1

    model_lines = "\n".join(
        f"  {m.split('/')[-1]}: {v['calls']} calls, {v['tokens']}tok, ${v['cost']:.4f}"
        for m, v in model_agg.items()
    )

    error_block = f"\n\nПроблема:\n<code>{_safe_html(error[:400])}</code>" if error else ""

    text = (
        f"{icon} <b>{_issue_link(num, title)}</b> — {status}\n"
        f"Pipeline: Spec → Code → Tests → Review → Merge\n"
        f"{error_block}\n"
        f"\nРезультат:\n{chr(10).join(result_lines)}\n"
        f"\nСтоимость:\n"
        f"  Факт: ${actual:.4f}\n"
        f"  Sonnet-only: ${sonnet:.4f}\n"
        f"  Экономия: ${saved:.4f}\n"
        f"\nМодели:\n{model_lines}"
    )
    await send_message(text)
    logger.info("Task summary sent for #%d: actual=$%.5f saved=$%.5f", num, actual, saved)


async def send_approval_request(
    title: str, risk: str, files_count: int, review_verdict: str,
    pr_url: str, issue_id: int
) -> str:
    """Sends PR approval card. Returns 'merge'|'reject'|'rework'."""
    prefix = f"approval_{issue_id}"
    q: asyncio.Queue = asyncio.Queue(maxsize=1)
    _approval_queues[prefix] = q

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Merge",      callback_data=f"{prefix}_merge"),
        InlineKeyboardButton("Отклонить", callback_data=f"{prefix}_reject"),
        InlineKeyboardButton("Доработать", callback_data=f"{prefix}_rework"),
    ]])

    review_icon = "✅" if review_verdict == "APPROVE" else "⚠️"
    msg_text = (
        f"<b>{_issue_link(issue_id, title)}</b>\n"
        f"Risk: {risk} | {files_count} files\n"
        f"Tests: passed | Review: {review_icon} {review_verdict}\n\n"
        f'<a href="{pr_url}">Открыть PR</a>'
    )
    await _app.bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=msg_text,
        reply_markup=keyboard,
        parse_mode="HTML",
        disable_web_page_preview=True,
    )
    logger.info("Approval request sent for prefix=%s, waiting...", prefix)

    action = await asyncio.wait_for(q.get(), timeout=86400)
    logger.info("Approval received: prefix=%s action=%s", prefix, action)
    _approval_queues.pop(prefix, None)
    return action


async def send_spec_approval_request(
    title: str, risk: str, spec: str, issue_id: int
) -> tuple[str, str]:
    """Sends spec plan with approve/clarify/cancel buttons.
    Returns (action, clarification_text).
    """
    prefix = f"spec_{issue_id}"
    q: asyncio.Queue = asyncio.Queue(maxsize=1)
    _approval_queues[prefix] = q

    summary = _extract_spec_summary(spec)
    msg_text = (
        f"<b>{_issue_link(issue_id, title)}</b>\n"
        f"Risk: {risk}\n\n"
        f"{_safe_html(summary)}"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("Принять",  callback_data=f"{prefix}_approve"),
        InlineKeyboardButton("Уточнить", callback_data=f"{prefix}_clarify"),
        InlineKeyboardButton("Отменить", callback_data=f"{prefix}_cancel"),
    ]])

    await _app.bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=msg_text,
        reply_markup=keyboard,
        parse_mode="HTML",
    )
    logger.info("Spec approval sent for prefix=%s, waiting...", prefix)

    action = await asyncio.wait_for(q.get(), timeout=86400)
    logger.info("Spec approval received: prefix=%s action=%s", prefix, action)
    _approval_queues.pop(prefix, None)

    clarification = ""
    if action == "clarify":
        await _app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text="Опишите что изменить в плане:",
            parse_mode=None,
        )
        text_prefix = f"text_{issue_id}"
        tq: asyncio.Queue = asyncio.Queue(maxsize=1)
        _approval_queues[text_prefix] = tq
        clarification = await asyncio.wait_for(tq.get(), timeout=86400)
        _approval_queues.pop(text_prefix, None)

    return action, clarification


def _extract_spec_summary(spec: str) -> str:
    lines = spec.splitlines()
    sections: list[str] = []
    current: list[str] = []
    capture_headers = {
        "1. Summary", "4. Files allowed to change",
        "5. Files FORBIDDEN", "7. Tests to write",
        "8. Acceptance criteria",
    }
    capturing = False
    for line in lines:
        stripped = line.strip()
        is_header = any(h in stripped for h in capture_headers)
        if is_header:
            if current:
                sections.append("\n".join(current))
            current = [line]
            capturing = True
        elif capturing and stripped.startswith(("1.", "2.", "3.", "4.", "5.", "6.", "7.", "8.", "9.", "10.")):
            if current:
                sections.append("\n".join(current))
            current = []
            capturing = False
        elif capturing:
            current.append(line)
    if current:
        sections.append("\n".join(current))
    result = "\n\n".join(sections)
    return result[:1800] if result else spec[:1000]


def update_task_status(issue_number: int, title: str, status: str):
    _active_tasks[issue_number] = {"title": title, "status": status}


async def _callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    logger.info("Callback received: data=%s", query.data)
    try:
        await query.answer()
        data = query.data
        parts = data.rsplit("_", 1)
        if len(parts) != 2:
            logger.warning("Unexpected callback_data format: %s", data)
            return
        prefix, action = parts
        logger.info("prefix=%s action=%s queues=%s", prefix, action, list(_approval_queues.keys()))
        if prefix in _approval_queues:
            q = _approval_queues[prefix]
            if q.empty():
                await q.put(action)
                logger.info("Put action '%s' into queue for %s", action, prefix)
            else:
                logger.info("Queue already has a result, ignoring duplicate press")
            _action_labels = {
                "merge": "Merge",
                "reject": "Отклонено",
                "rework": "Доработать",
                "approve": "Принято",
                "clarify": "Уточнить",
                "cancel": "Отменено",
            }
            label = _action_labels.get(action, action)
            try:
                await query.edit_message_text(text=f"— {label}", parse_mode=None)
            except Exception as e:
                logger.warning("edit_message_text failed (%s), removing keyboard only", e)
                try:
                    await query.edit_message_reply_markup(reply_markup=None)
                except Exception as e2:
                    logger.warning("edit_message_reply_markup also failed: %s", e2)
        else:
            logger.warning("No queue for prefix=%s (already handled or old message)", prefix)
    except Exception as e:
        logger.exception("Error in callback_handler: %s", e)


async def _message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    for key, q in list(_approval_queues.items()):
        if key.startswith("text_") and q.empty():
            await q.put(text)
            logger.info("Clarification text received for %s", key)
            await update.message.reply_text("Принято, передаю архитектору...")
            return


async def send_model_health_alert(status: str, details: str) -> str:
    """Sends model health alert with action buttons.
    status: 'unreachable' | 'wrong_model'
    Returns: 'retry' | 'continue' | 'stop'
    """
    prefix = "model_health"
    q: asyncio.Queue = asyncio.Queue(maxsize=1)
    _approval_queues[prefix] = q

    if status == "unreachable":
        icon = "🔴"
        msg = f"{icon} <b>Qwen недоступен</b>\n<code>{_safe_html(details)}</code>"
        buttons = [
            InlineKeyboardButton("🔄 Повторить", callback_data=f"{prefix}_retry"),
            InlineKeyboardButton("▶️ Продолжить", callback_data=f"{prefix}_continue"),
            InlineKeyboardButton("⏹ Остановить", callback_data=f"{prefix}_stop"),
        ]
        msg += "\n\n▶️ Продолжить = Qwen-вызовы пойдут через Haiku fallback"
    else:
        icon = "🟡"
        msg = (
            f"{icon} <b>Не та модель в vLLM</b>\n{_safe_html(details)}\n\n"
            f"Чтобы исправить — запустите на машине 5090:\n"
            f"<code>bash ~/ai-orchestrator/infra/qwen-server.sh</code>\n\n"
            f"▶️ С текущей = используется загруженная модель\n"
            f"☁️ Через Haiku = все Qwen-вызовы идут в Claude Haiku"
        )
        buttons = [
            InlineKeyboardButton("▶️ С текущей моделью", callback_data=f"{prefix}_continue"),
            InlineKeyboardButton("☁️ Через Haiku", callback_data=f"{prefix}_haiku"),
            InlineKeyboardButton("⏹ Остановить", callback_data=f"{prefix}_stop"),
        ]

    await _app.bot.send_message(
        chat_id=TELEGRAM_CHAT_ID,
        text=msg,
        reply_markup=InlineKeyboardMarkup([buttons]),
        parse_mode="HTML",
    )

    action = await asyncio.wait_for(q.get(), timeout=86400)
    _approval_queues.pop(prefix, None)
    logger.info("Model health action chosen: %s", action)
    return action


async def _status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _active_tasks:
        await update.message.reply_text("Нет активных задач.")
        return
    lines = ["<b>Активные задачи:</b>"]
    for num, info in _active_tasks.items():
        lines.append(f"  #{num} {info['title']} — {info['status']}")
    await update.message.reply_text("\n".join(lines), parse_mode="HTML")


async def start_polling():
    global _app
    _app = _make_app()
    _app.add_handler(CallbackQueryHandler(_callback_handler))
    _app.add_handler(CommandHandler("status", _status_command))
    _app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, _message_handler))
    await _app.initialize()
    await _app.start()
    await _app.updater.start_polling(
        drop_pending_updates=True,
        allowed_updates=["message", "callback_query", "inline_query"],
    )
    logger.info("Telegram polling started")


async def stop_polling():
    if _app:
        try:
            await _app.updater.stop()
            await _app.stop()
            await _app.shutdown()
        except Exception as e:
            logger.debug("stop_polling: %s", e)
