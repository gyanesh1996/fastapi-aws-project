"""Station 4, the Telegram bot: make Shorts from your phone and approve them.

Run:  python -m app.bot      (keep this window open; Ctrl+C stops the bot)

In Telegram:
  any text message       -> it's an idea: the script, poster and video come back for review
  /new                   -> Claude picks today's topic
  buttons under a video  -> Approve / Reject / Redo / Use my voice
"""
import asyncio
import json
import logging
import secrets
import sys
import textwrap
from datetime import datetime
from pathlib import Path

from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update
from telegram.error import NetworkError
from telegram.ext import Application, CallbackQueryHandler, CommandHandler, ContextTypes, MessageHandler, filters

from app.config import DRAFTS_DIR, RECORDINGS_DIR, ROOT, TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID
from app.costs import USD_TO_INR
from app.poster import make_poster
from app.video import make_video
from app.writer import save_draft, write_short

HELP = (
    "Send me an idea as a message (Hinglish or English), for example:\n"
    "\"chai ke saath roz biscuit\"\n\n"
    "I'll write the script, make the poster and video, and send it back for you to check.\n\n"
    "/new: I pick today's topic\n"
    "/resend: send again any video that wasn't confirmed as delivered\n"
    "/cancel: stop waiting for a redo or voice note"
)

owner_id = int(TELEGRAM_CHAT_ID) if TELEGRAM_CHAT_ID else None
pairing_code = None if owner_id else f"{secrets.randbelow(10000):04d}"
busy = asyncio.Lock()  # one Short at a time


# ---------- Drafts ----------

def draft_id(path: Path) -> str:
    return path.stem[:15]  # "20261001-130544": short enough for Telegram's button data


def draft_file(short_id: str) -> Path | None:
    return next(iter(DRAFTS_DIR.glob(f"{short_id}-*.json")), None)


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, draft: dict) -> None:
    path.write_text(json.dumps(draft, ensure_ascii=False, indent=2), encoding="utf-8")


def buttons(short_id: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ Approve", callback_data=f"approve:{short_id}"),
         InlineKeyboardButton("❌ Reject", callback_data=f"reject:{short_id}")],
        [InlineKeyboardButton("✏️ Redo", callback_data=f"redo:{short_id}"),
         InlineKeyboardButton("🎙️ Use my voice", callback_data=f"voice:{short_id}")],
    ])


def summary(draft: dict) -> str:
    """The caption under the video: what you need to decide whether to approve."""
    c, poster = draft["content"], draft.get("poster", {})
    parts = [
        f"🎬 {c['youtube_title']}",
        f"📌 {c['pillar']} · {c['format'].replace('_', ' ')}",
        f"🔎 Fact-check: {c['fact_check']['verdict'].upper()}\n"
        + textwrap.shorten(c["fact_check"]["notes"], 380, placeholder="…"),
    ]
    problems = draft.get("grounding_problems")
    parts.append("⚠️ SOURCE CHECK FAILED, don't approve: " + "; ".join(problems) if problems
                 else f"✅ Sources checked ({len(c['sources'])} quote{'' if len(c['sources']) == 1 else 's'})")
    if review := poster.get("review"):
        issues = "; ".join(review["issues"] + [f"unreadable words: {', '.join(poster['missing_words'])}"]
                           if poster.get("missing_words") else review["issues"])
        parts.append(f"🖼️ Poster check: {review['verdict'].upper()}" + (f": {issues}" if issues else ""))
    voice = draft.get("video", {}).get("voice", "")
    cost = draft["usage"]["total_cost_usd"] + poster.get("usage", {}).get("cost_usd", 0)
    parts.append(f"🎙️ {'Your voice' if voice.startswith('own:') else 'AI voice'} · 💰 ₹{cost * USD_TO_INR:.1f}")
    return "\n\n".join(parts)[:1024]  # Telegram's caption limit


async def send_for_review(bot: Bot, path: Path) -> bool:
    """Send the video with its buttons; returns whether Telegram confirmed it.

    No automatic retries: on a slow connection Telegram can receive the video even though
    the confirmation times out, so retrying sends duplicates. You decide with /resend."""
    draft = load(path)
    try:
        with open(draft["video"]["path"], "rb") as video:
            await bot.send_video(
                owner_id, video, caption=summary(draft), reply_markup=buttons(draft_id(path)),
                supports_streaming=True, width=1080, height=1920, duration=int(draft["video"]["seconds"]),
            )
    except NetworkError as error:
        logging.warning("Sending the video wasn't confirmed: %s", error)
        return False
    draft["sent_at"] = datetime.now().isoformat(timespec="seconds")
    save(path, draft)
    return True


def unsent_drafts() -> list[Path]:
    """Finished videos that Telegram never confirmed receiving."""
    return [p for p in sorted(DRAFTS_DIR.glob("*.json"))
            if (d := load(p)).get("status") == "pending" and d.get("video") and not d.get("sent_at")]


# ---------- Making Shorts ----------

async def produce(message: Message, context: ContextTypes.DEFAULT_TYPE, idea: str | None,
                  feedback: dict | None = None, redo_of: str | None = None) -> None:
    """Writer -> poster -> video, with progress updates, then send it for review."""
    if busy.locked():
        await message.reply_text("⏳ I'm still working on the last one. Send this again in a minute.")
        return
    async with busy:
        status = await message.reply_text("✍️ Writing the script… (about 30 seconds)")
        try:
            result = await asyncio.to_thread(write_short, idea, None, feedback)
            path = Path(save_draft(result, idea, redo_of))
            await status.edit_text("🖼️ Making the poster and checking it…")
            await asyncio.to_thread(make_poster, path)
            await status.edit_text("🎬 Making the video… (about a minute)")
            await asyncio.to_thread(make_video, path)
        except Exception as error:
            logging.exception("Making a Short failed")
            await status.edit_text(f"⚠️ Something went wrong: {error}")
            return
        await status.delete()
        if not await send_for_review(context.bot, path):
            await message.reply_text("⚠️ The video is ready but Telegram didn't confirm it arrived (slow internet?). "
                                     "If you don't see it in a few minutes, send /resend.")


async def remake_with_voice(message: Message, context: ContextTypes.DEFAULT_TYPE, path: Path, recording: Path) -> None:
    async with busy:
        status = await message.reply_text("🎬 Making the video with your voice… (about a minute)")
        try:
            await asyncio.to_thread(make_video, path, recording)
        except Exception as error:
            logging.exception("Remaking with own voice failed")
            await status.edit_text(f"⚠️ Something went wrong: {error}")
            return
        await status.delete()
        draft = load(path)
        draft.pop("sent_at", None)  # it's a new video, so it needs sending again
        save(path, draft)
        if not await send_for_review(context.bot, path):
            await message.reply_text("⚠️ The video is ready but Telegram didn't confirm it arrived. "
                                     "If you don't see it in a few minutes, send /resend.")


# ---------- Telegram handlers ----------

def is_owner(update: Update) -> bool:
    return owner_id is not None and update.effective_chat is not None and update.effective_chat.id == owner_id


def remember_owner(chat_id: int) -> None:
    with open(ROOT / ".env", "a", encoding="utf-8") as env:
        env.write(f"\nTELEGRAM_CHAT_ID={chat_id}\n")


async def on_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global owner_id
    if owner_id is None:
        if context.args and context.args[0] == pairing_code:
            owner_id = update.effective_chat.id
            remember_owner(owner_id)
            print(f"Connected to your Telegram (chat {owner_id}).")
            await update.message.reply_text("✅ Connected! I'll only listen to you.\n\n" + HELP)
        else:
            await update.message.reply_text("Send /start followed by the 4-digit code shown on your computer.")
    elif is_owner(update):
        await update.message.reply_text(HELP)


async def on_new(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_owner(update):
        await produce(update.message, context, idea=None)


async def on_resend(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update):
        return
    paths = unsent_drafts()
    if not paths:
        await update.message.reply_text("Nothing to resend: every video was delivered.")
    for path in paths:
        await send_for_review(context.bot, path)


async def on_error(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    if isinstance(context.error, NetworkError):
        logging.warning("Network problem, will keep retrying: %s", context.error)  # usually the internet dropped
    else:
        logging.error("Unexpected error", exc_info=context.error)


async def on_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if is_owner(update):
        context.user_data.pop("waiting", None)
        await update.message.reply_text("OK. Send a new idea any time.")


async def on_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update):
        return
    text = update.message.text.strip()
    waiting = context.user_data.pop("waiting", None)
    if waiting and waiting[0] == "redo" and (path := draft_file(waiting[1])):
        draft = load(path)
        draft["status"] = "redone"
        save(path, draft)
        feedback = {"previous": draft["content"], "request": text}
        await produce(update.message, context, draft["idea"], feedback, redo_of=waiting[1])
        return
    if waiting and waiting[0] == "voice":
        await update.message.reply_text("(OK, not waiting for a voice note any more. Treating this as a new idea.)")
    await produce(update.message, context, text)


async def on_voice(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    if not is_owner(update):
        return
    waiting = context.user_data.get("waiting")
    if not waiting or waiting[0] != "voice" or not (path := draft_file(waiting[1])):
        await update.message.reply_text("To use your voice, first tap 🎙️ Use my voice under a video. "
                                        "To send an idea, type it as a message.")
        return
    if busy.locked():
        await update.message.reply_text("⏳ I'm still working on the last one. Send the voice note again in a minute.")
        return
    context.user_data.pop("waiting")
    audio = update.message.voice or update.message.audio
    RECORDINGS_DIR.mkdir(parents=True, exist_ok=True)
    suffix = Path(audio.file_name).suffix if getattr(audio, "file_name", None) else ".ogg"
    recording = RECORDINGS_DIR / f"{waiting[1]}-{datetime.now():%H%M%S}{suffix}"
    await (await audio.get_file()).download_to_drive(recording)
    await remake_with_voice(update.message, context, path, recording)


async def on_button(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query = update.callback_query
    if not is_owner(update):
        await query.answer()
        return
    await query.answer()
    action, short_id = query.data.split(":", 1)
    path = draft_file(short_id)
    if path is None:
        await query.message.reply_text("I can't find that draft any more.")
        return
    draft = load(path)

    if action in ("approve", "reject"):
        draft["status"] = "approved" if action == "approve" else "rejected"
        draft[f"{draft['status']}_at"] = datetime.now().isoformat(timespec="seconds")
        save(path, draft)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.message.reply_text(
            "✅ Approved! It's ready for YouTube (the upload step comes in Phase 5)." if action == "approve"
            else "❌ Rejected. Send a new idea any time."
        )
    elif action == "redo":
        context.user_data["waiting"] = ("redo", short_id)
        await query.message.reply_text("✏️ What should change? Reply with a message, for example "
                                       "\"make it shorter\", \"less English\" or \"stronger hook\".")
    elif action == "voice":
        context.user_data["waiting"] = ("voice", short_id)
        await query.message.reply_text(
            "🎙️ Read this aloud like you're talking to a friend, then send it as a voice note:\n\n"
            + draft["content"]["script_hinglish"]
        )


def main() -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    if not TELEGRAM_BOT_TOKEN:
        sys.exit("Add TELEGRAM_BOT_TOKEN to .env first (see README, Phase 4).")
    logging.basicConfig(format="%(asctime)s %(levelname)s %(message)s", level=logging.INFO)
    logging.getLogger("httpx").setLevel(logging.WARNING)  # its request log lines contain the bot token

    async def on_startup(application: Application) -> None:
        if owner_id and (count := len(unsent_drafts())):
            await application.bot.send_message(
                owner_id, f"I'm back online. {count} video(s) weren't confirmed as delivered. "
                          "If you didn't get them, send /resend.")

    # Generous timeouts: on a slow connection, uploading one video can take a couple of minutes.
    app = (Application.builder().token(TELEGRAM_BOT_TOKEN)
           .connect_timeout(30).read_timeout(300).write_timeout(300).media_write_timeout(300)
           .post_init(on_startup).build())
    app.add_error_handler(on_error)
    app.add_handler(CommandHandler("start", on_start))
    app.add_handler(CommandHandler("new", on_new))
    app.add_handler(CommandHandler("resend", on_resend))
    app.add_handler(CommandHandler("cancel", on_cancel))
    app.add_handler(CallbackQueryHandler(on_button))
    app.add_handler(MessageHandler(filters.VOICE | filters.AUDIO, on_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, on_text))

    print("The bot is running. Press Ctrl+C to stop it.")
    if pairing_code:
        print(f"\n>>> To connect your phone: open the bot in Telegram and send:  /start {pairing_code}\n")
    app.run_polling()


if __name__ == "__main__":
    main()
