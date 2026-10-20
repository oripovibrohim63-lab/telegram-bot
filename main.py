
import os
import io
import asyncio
import logging
from collections import defaultdict, deque

from google import genai
from google.genai import types

from telegram import Update
from telegram.error import TelegramError
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)

# =========================
# SOZLAMALAR
# =========================

BOT_TOKEN = os.environ["BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

MODEL = os.getenv("GEMINI_MODEL", "gemini-flash-latest")
IMAGE_MODEL = os.getenv("IMAGE_MODEL", "gemini-2.5-flash-image")

MAX_TEXT_LENGTH = 12000
MAX_MEDIA_SIZE = 19 * 1024 * 1024
MAX_REPLY_LENGTH = 3900

ai = genai.Client(api_key=GEMINI_API_KEY)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Har bir foydalanuvchi uchun vaqtinchalik suhbat xotirasi.
history = defaultdict(lambda: deque(maxlen=12))

SYSTEM_PROMPT = """
Sen foydali, aqlli va xushmuomala AI yordamchisan.
Asosan o'zbek tilida javob ber.
Savol boshqa tilda bo'lsa, o'sha tilda javob bera ol.
Bilmagan narsangni to'qib chiqarma.
Rasm yoki audio yuborilsa, uning mazmunini tahlil qil.
Javoblaringni aniq va tushunarli yoz.
"""


# =========================
# YORDAMCHI FUNKSIYALAR
# =========================

async def generate(contents, model=None):
    """Gemini so'rovini asosiy event loopni to'smasdan bajaradi."""
    response = await asyncio.to_thread(
        ai.models.generate_content,
        model=model or MODEL,
        contents=contents,
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            max_output_tokens=4096,
        ),
    )

    if not response.text:
        raise RuntimeError("Gemini bo'sh javob qaytardi.")

    return response.text.strip()


async def send_long(message, text):
    """Uzun javobni Telegram xabarlariga bo'lib yuboradi."""
    text = (text or "").strip()

    if not text:
        text = "Kechirasiz, javob olinmadi."

    for start_index in range(0, len(text), MAX_REPLY_LENGTH):
        await message.reply_text(
            text[start_index:start_index + MAX_REPLY_LENGTH]
        )


async def get_media(message):
    """Ovoz yoki rasmni Telegram'dan yuklab oladi."""
    media = None
    mime_type = None

    if message.voice:
        media = message.voice
        mime_type = message.voice.mime_type or "audio/ogg"

    elif message.audio:
        media = message.audio
        mime_type = message.audio.mime_type or "audio/mpeg"

    elif message.photo:
        media = message.photo[-1]
        mime_type = "image/jpeg"

    elif message.document:
        doc = message.document
        doc_mime = doc.mime_type or ""

        if doc_mime.startswith(("audio/", "image/")):
            media = doc
            mime_type = doc_mime

    if media is None:
        return None

    if media.file_size and media.file_size > MAX_MEDIA_SIZE:
        raise ValueError(
            "Fayl juda katta. 19 MB dan kichik fayl yuboring."
        )

    telegram_file = await media.get_file()
    data = bytes(await telegram_file.download_as_bytearray())

    if len(data) > MAX_MEDIA_SIZE:
        raise ValueError("Yuklangan fayl hajmi limitdan oshdi.")

    return data, mime_type


async def safe_delete(message):
    try:
        await message.delete()
    except TelegramError:
        pass


# =========================
# /start
# =========================

async def start(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await update.effective_message.reply_text(
        "Salom! Men AI yordamchiman 🤖\n\n"
        "Menga savolingizni yozing yoki rasm va ovozli xabar yuboring.\n\n"
        "/help — yordam\n"
        "/reset — suhbat xotirasini tozalash\n"
        "/image tavsif — AI rasm yaratish\n"
        "/translate English | Salom — tarjima"
    )


# =========================
# /help
# =========================

async def help_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    await start(update, context)


# =========================
# /reset
# =========================

async def reset(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    user = update.effective_user

    if user:
        history.pop(user.id, None)

    await update.effective_message.reply_text(
        "Suhbat xotirasi tozalandi. Yangi savol yuboring!"
    )


# =========================
# /image — RASM YARATISH
# =========================

async def image_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    prompt = " ".join(context.args).strip()

    if not prompt:
        await message.reply_text(
            "Misol:\n/image O'zbekiston tog'lari manzarasi"
        )
        return

    if len(prompt) > 2000:
        await message.reply_text("Rasm tavsifi juda uzun.")
        return

    status = await message.reply_text("🎨 Rasm yaratilmoqda...")

    try:
        response = await asyncio.to_thread(
            ai.models.generate_content,
            model=IMAGE_MODEL,
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["IMAGE", "TEXT"]
            ),
        )

        sent = False

        for part in response.parts or []:
            if part.inline_data:
                picture = part.as_image()
                buffer = io.BytesIO()
                picture.save(buffer, format="PNG")
                buffer.seek(0)

                await message.reply_photo(
                    photo=buffer,
                    filename="ai_image.png",
                )
                sent = True

        if not sent:
            await status.edit_text(
                "Model rasm qaytarmadi. IMAGE_MODEL va API "
                "imkoniyatlarini tekshiring."
            )
            return

        await safe_delete(status)

    except Exception:
        logger.exception("Rasm yaratishda xato")

        await status.edit_text(
            "Rasm yaratilmadi. API kaliti, model nomi, "
            "hisob limiti va model imkoniyatlarini tekshiring."
        )


# =========================
# /translate — TARJIMA
# =========================

async def translate_command(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    text = " ".join(context.args).strip()

    if "|" not in text:
        await message.reply_text(
            "Foydalanish:\n"
            "/translate English | Salom dunyo"
        )
        return

    language, original = (
        item.strip() for item in text.split("|", 1)
    )

    if not language or not original:
        await message.reply_text(
            "Til va tarjima qilinadigan matnni kiriting."
        )
        return

    if len(original) > MAX_TEXT_LENGTH:
        await message.reply_text("Tarjima matni juda uzun.")
        return

    try:
        result = await generate(
            "Quyidagi matnni "
            + language
            + " tiliga tarjima qil. Ma'nosini saqla. "
              "Faqat tarjimani qaytar:\n\n"
            + original
        )
        await send_long(message, result)

    except Exception:
        logger.exception("Tarjima xatosi")
        await message.reply_text(
            "Tarjima bajarilmadi. API kaliti, model va "
            "hisob limitini tekshiring."
        )


# =========================
# MATN, RASM VA OVOZLI XABARLAR
# =========================

async def answer(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE,
):
    message = update.effective_message
    user = update.effective_user

    if not message or not user:
        return

    question = (message.text or message.caption or "").strip()

    if len(question) > MAX_TEXT_LENGTH:
        await message.reply_text(
            "Xabar juda uzun. Iltimos, qisqartirib yuboring."
        )
        return

    try:
        media = await get_media(message)
    except ValueError as exc:
        await message.reply_text(str(exc))
        return
    except Exception:
        logger.exception("Media yuklashda xato")
        await message.reply_text(
            "Faylni yuklab bo'lmadi. Boshqa fayl yuborib ko'ring."
        )
        return

    if not question and media is None:
        return

    status = await message.reply_text("🤔 Javob tayyorlayapman...")

    try:
        if media:
            data, mime_type = media

            if question:
                instruction = question
            elif mime_type.startswith("audio/"):
                instruction = (
                    "Ovozli xabarni tinglab, undagi nutqni matnga "
                    "ko'chir va mazmunini qisqacha tushuntir."
                )
            else:
                instruction = (
                    "Ushbu rasmni tahlil qil va unda nimalar "
                    "tasvirlanganini tushuntir."
                )

            parts = [
                types.Part.from_text(text=instruction),
                types.Part.from_bytes(
                    data=data,
                    mime_type=mime_type,
                ),
            ]

            result = await generate(parts)

        else:
            conversation = [
                {
                    "role": "user",
                    "parts": [{"text": SYSTEM_PROMPT}],
                },
                {
                    "role": "model",
                    "parts": [{
                        "text": "Tushundim. Savollarga yordam beraman."
                    }],
                },
            ]

            conversation.extend(list(history[user.id]))
            conversation.append({
                "role": "user",
                "parts": [{"text": question}],
            })

            result = await generate(conversation)

        if not result:
            result = "Kechirasiz, bu safar javob olinmadi."

        # Faqat matnli suhbatni tarixda saqlaymiz.
        if not media:
            history[user.id].append({
                "role": "user",
                "parts": [{"text": question}],
            })
            history[user.id].append({
                "role": "model",
                "parts": [{"text": result[:12000]}],
            })

        await send_long(message, result)
        await safe_delete(status)

    except Exception:
        logger.exception("AI javobida xato")

        try:
            await status.edit_text(
                "⚠️ Javob olinmadi. API kaliti, model nomi, "
                "internet aloqasi yoki API limitini tekshiring. "
                "Batafsil xato server logida saqlanadi."
            )
        except TelegramError:
            await message.reply_text(
                "Javob olinmadi. Birozdan keyin qayta urinib ko'ring."
            )


# =========================
# UMUMIY XATOLAR
# =========================

async def global_error(
    update: object,
    context: ContextTypes.DEFAULT_TYPE,
):
    logger.error(
        "Kutilmagan bot xatosi",
        exc_info=context.error,
    )


# =========================
# BOTNI ISHGA TUSHIRISH
# =========================

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("reset", reset))
    app.add_handler(CommandHandler("image", image_command))
    app.add_handler(CommandHandler("translate", translate_command))

    # Oddiy matnlar
    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            answer,
        )
    )

    # Ovozli xabarlar
    app.add_handler(
        MessageHandler(
            filters.VOICE,
            answer,
        )
    )

    # Oddiy audio fayllar, rasmlar va mos hujjatlar
    app.add_handler(
        MessageHandler(
            filters.PHOTO | filters.AUDIO | filters.Document.ALL,
            answer,
        )
    )

    app.add_error_handler(global_error)

    logger.info("AI Telegram bot ishga tushmoqda...")
    app.run_polling()


if __name__ == "__main__":
    main()
