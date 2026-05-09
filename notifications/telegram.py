import asyncio
import logging

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters
from telegram.request import HTTPXRequest

from config.settings import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, TELEGRAM_PROXY

logger = logging.getLogger(__name__)

# approval_queue: receives (prefix, action) tuples from callback handler
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
    # Large pool: poller + pipeline sends run concurrently, default pool (1-2) causes PoolTimeout
    request = HTTPXRequest(connection_pool_size=16, proxy=proxy)
    builder = builder.request(request)
    return builder.build()


def _safe_html(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def send_message(text: str):
    await _app.bot.send_message(chat_id=TELEGRAM_CHAT_ID, text=text, parse_mode="HTML")


async def send_approval_request(text: str, pr_url: str, issue_id: int) -> str:
    """Sends Merge/Reject/Rework buttons. Returns 'merge'|'reject'|'rework'."""
    prefix = f"approval_{issue_id}"
    q: asyncio.Queue = asyncio.Queue(maxsize=1)
    _approval_queues[prefix] = q

    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Merge",        callback_data=f"{prefix}_merge"),
        InlineKeyboardButton("❌ Отклонить",    callback_data=f"{prefix}_reject"),
        InlineKeyboardButton("🔄 Доработать",  callback_data=f"{prefix}_rework"),
    ]])

    msg_text = (
        f"{_safe_html(text)}\n\n"
        f'<a href="{pr_url}">Открыть PR</a>\n\n'
        f"Жду решения:"
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
    """Sends spec plan with [✅ Принять] [✏️ Уточнить] [❌ Отменить] buttons.
    Returns (action, clarification_text).
    action: 'approve' | 'clarify' | 'cancel'
    """
    prefix = f"spec_{issue_id}"
    q: asyncio.Queue = asyncio.Queue(maxsize=1)
    _approval_queues[prefix] = q

    # Extract key sections from spec for summary
    summary = _extract_spec_summary(spec)

    msg_text = (
        f"📋 <b>План готов: {_safe_html(title)}</b>\n"
        f"Risk: {risk}\n\n"
        f"{_safe_html(summary)}\n\n"
        f"Подтвердите план:"
    )
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("✅ Принять план",   callback_data=f"{prefix}_approve"),
        InlineKeyboardButton("✏️ Уточнить",       callback_data=f"{prefix}_clarify"),
        InlineKeyboardButton("❌ Отменить задачу", callback_data=f"{prefix}_cancel"),
    ]])

    sent = await _app.bot.send_message(
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
        # ask for clarification text
        await _app.bot.send_message(
            chat_id=TELEGRAM_CHAT_ID,
            text="✏️ Опишите что изменить в плане:",
            parse_mode=None,
        )
        # wait for a text message reply
        text_prefix = f"text_{issue_id}"
        tq: asyncio.Queue = asyncio.Queue(maxsize=1)
        _approval_queues[text_prefix] = tq
        clarification = await asyncio.wait_for(tq.get(), timeout=86400)
        _approval_queues.pop(text_prefix, None)

    return action, clarification


def _extract_spec_summary(spec: str) -> str:
    """Pulls Summary, allowed/forbidden files and tests from the spec."""
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
        data = query.data  # e.g. "approval_1_merge"
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
            try:
                await query.edit_message_text(
                    text=f"✅ Выбрано: {action}",
                    parse_mode=None,
                )
            except Exception as e:
                logger.debug("edit_message_text: %s", e)
        else:
            logger.warning("No queue for prefix=%s (already handled or old message)", prefix)
    except Exception as e:
        logger.exception("Error in callback_handler: %s", e)


async def _message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handles plain text replies (used for clarification after ✏️ Уточнить)."""
    if not update.message or not update.message.text:
        return
    text = update.message.text.strip()
    # find any waiting text queue
    for key, q in list(_approval_queues.items()):
        if key.startswith("text_") and q.empty():
            await q.put(text)
            logger.info("Clarification text received for %s", key)
            await update.message.reply_text("✅ Принято, передаю архитектору...")
            return


async def _status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _active_tasks:
        await update.message.reply_text("Нет активных задач.")
        return
    lines = ["<b>Активные задачи:</b>"]
    for num, info in _active_tasks.items():
        lines.append(f"• #{num} {info['title']} → <i>{info['status']}</i>")
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
