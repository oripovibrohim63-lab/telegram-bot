
import os
import io
import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from collections import defaultdict, deque

from google import genai
from google.genai import types

from telegram import Update, ChatPermissions, InlineKeyboardButton, InlineKeyboardMarkup
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
# GURUH / KANAL BOSHQARUVI
# =========================

# Kanalga post yuborish uchun: /post @kanal_username post matni
# Bot kanal/guruhda administrator bo'lishi va kerakli huquqlarga ega bo'lishi shart.
MANAGEMENT_HELP = (
    "🛠 Guruh va kanal boshqaruvi\n\n"
    "Guruhda admin xabarga REPLY qilib ishlatadi:\n"
    "/del — xabarni o'chirish\n"
    "/ban — foydalanuvchini guruhdan chiqarish\n"
    "/mute 10 — 10 daqiqaga yozishni cheklash\n"
    "/unmute — yozish cheklovini olib tashlash\n\n"
    "Kanalga post: /post @kanal_username post matni\n"
    "AI orqali boshqaruv: /manage va keyin vazifani oddiy tilda yozing.\n"
    "Masalan: /manage guruh qoidalarini yozib ber\n\n"
    "Xavfsizlik uchun ban/mute/del amallari faqat adminlar tomonidan bajariladi."
)


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
    music_keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🎵 Smile qo‘shig‘ini tinglash",
            url="https://oripovibrohim63-lab.github.io/telegram-bot/",
        )]
    ])

    await update.effective_message.reply_text(
        "Salom! Men AI yordamchiman 🤖\n\n"
        "Menga savolingizni yozing yoki rasm va ovozli xabar yuboring.\n\n"
        "/help — yordam\n"
        "/reset — suhbat xotirasini tozalash\n"
        "/image tavsif — AI rasm yaratish\n"
        "/translate English | Salom — tarjima\n"
        "/grouphelp — guruh/kanal boshqaruvi buyruqlari",
        reply_markup=music_keyboard,
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

    # Kanalga post yuborishni oddiy tilda so'rash: "kanalga post @kanal matn".
    chat = update.effective_chat
    lower_any = question.lower().strip()
    if question and lower_any.startswith(("kanalga post ", "kanalga joyla ")):
        raw = question.split(" ", 2)
        if len(raw) < 3:
            await message.reply_text("Misol: kanalga post @kanalim Salom, yangi post!")
            return
        context.args = raw[2].split()
        await post_to_channel(update, context)
        return
    if question and lower_any.startswith("kanalni boshqar"):
        await message.reply_text(
            "Kanalga post yuborish uchun: /post @kanal_username post matni\n"
            "Avval botni kanalga administrator qilib qo'shing.\n"
            "Barcha boshqaruv buyruqlari: /grouphelp"
        )
        return

    # Guruhdagi aniq boshqaruv buyruqlarini oddiy tilda ham tushunish.
    # Oddiy suhbatga aralashmasligi uchun faqat aniq buyruq iboralari tekshiriladi.
    if question and chat and chat.type in ("group", "supergroup"):
        lower_question = question.lower().strip()
        management_phrases = (
            "guruhni boshqar", "bu xabarni o'chir", "bu xabarni ochir",
            "shu xabarni o'chir", "shu xabarni ochir", "foydalanuvchini ban qil",
            "foydalanuvchini chekla", "shu odamni chekla", "shu odamni ban qil",
            "guruh qoidalarini yoz", "guruh qoidalarini tuz",
        )
        if any(lower_question.startswith(phrase) for phrase in management_phrases):
            if not await is_chat_admin(update, context):
                await message.reply_text("⛔ Guruhni boshqarish buyruqlarini faqat administrator ishlata oladi.")
                return
            if ("xabarni" in lower_question) and ("o'chir" in lower_question or "ochir" in lower_question):
                if not message.reply_to_message:
                    await message.reply_text("O'chiriladigan xabarga reply qilib yozing: Bu xabarni o'chir")
                    return
                try:
                    await message.reply_to_message.delete()
                    await message.reply_text("✅ Xabar o'chirildi.")
                except TelegramError:
                    await message.reply_text("Xabar o'chmadi. Botga xabarlarni o'chirish huquqini bering.")
                return
            if "ban qil" in lower_question or "guruhdan chiqar" in lower_question:
                target = message.reply_to_message.from_user if message.reply_to_message else None
                if not target:
                    await message.reply_text("Foydalanuvchining xabariga reply qilib: Shu odamni ban qil deb yozing.")
                    return
                try:
                    member = await context.bot.get_chat_member(chat.id, target.id)
                    if target.id == user.id or member.status in ("administrator", "creator"):
                        await message.reply_text("Bu foydalanuvchini ban qilish mumkin emas.")
                    else:
                        await context.bot.ban_chat_member(chat.id, target.id)
                        await message.reply_text(f"✅ {target.full_name} guruhdan chiqarildi.")
                except TelegramError:
                    await message.reply_text("Ban bajarilmadi. Bot huquqlarini tekshiring.")
                return
            if "chekla" in lower_question or "mute" in lower_question:
                target = message.reply_to_message.from_user if message.reply_to_message else None
                if not target:
                    await message.reply_text("Foydalanuvchining xabariga reply qilib: Shu odamni chekla 10 daqiqa deb yozing.")
                    return
                found = re.search(r"(\d+)", lower_question)
                minutes = int(found.group(1)) if found else 60
                if minutes < 1 or minutes > 10080:
                    await message.reply_text("Muddat 1–10080 daqiqa oralig'ida bo'lishi kerak.")
                    return
                try:
                    member = await context.bot.get_chat_member(chat.id, target.id)
                    if target.id == user.id or member.status in ("administrator", "creator"):
                        await message.reply_text("Bu foydalanuvchini cheklash mumkin emas.")
                    else:
                        await context.bot.restrict_chat_member(
                            chat.id, target.id,
                            permissions=ChatPermissions(can_send_messages=False),
                            until_date=datetime.now(timezone.utc) + timedelta(minutes=minutes),
                        )
                        await message.reply_text(f"✅ {target.full_name} {minutes} daqiqaga cheklab qo'yildi.")
                except TelegramError:
                    await message.reply_text("Cheklash bajarilmadi. Bot huquqlarini tekshiring.")
                return
            # Qoidalar yoki umumiy boshqaruv bo'yicha AI yordam.
            context.args = [question]
            await manage_with_ai(update, context)
            return

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

    status = await message.reply_text("🤔 Javob tayyorlanmoqda...")

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
# GURUH / KANAL BOSHQARUVI
# =========================

async def is_chat_admin(update: Update, context: ContextTypes.DEFAULT_TYPE, chat_id=None):
    """Foydalanuvchi ko'rsatilgan chatda administrator ekanini tekshiradi."""
    user = update.effective_user
    target_chat = chat_id if chat_id is not None else update.effective_chat.id
    if not user:
        return False
    try:
        member = await context.bot.get_chat_member(target_chat, user.id)
        return member.status in ("administrator", "creator")
    except TelegramError:
        return False


async def require_group_admin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat = update.effective_chat
    message = update.effective_message
    if not chat or chat.type not in ("group", "supergroup"):
        await message.reply_text("Bu buyruqni guruh ichida ishlating.")
        return False
    if not await is_chat_admin(update, context):
        await message.reply_text("⛔ Bu amalni faqat guruh administratori bajara oladi.")
        return False
    return True


async def management_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.effective_message.reply_text(MANAGEMENT_HELP)


async def delete_replied_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not await require_group_admin(update, context):
        return
    if not message.reply_to_message:
        await message.reply_text("O'chiriladigan xabarga reply qilib /del yozing.")
        return
    try:
        await message.reply_to_message.delete()
        await message.reply_text("✅ Xabar o'chirildi.")
    except TelegramError:
        await message.reply_text("Xabar o'chmadi. Botga xabarlarni o'chirish huquqini bering.")


async def ban_replied_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not await require_group_admin(update, context):
        return
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if not target:
        await message.reply_text("Foydalanuvchining xabariga reply qilib /ban yozing.")
        return
    if target.id == update.effective_user.id:
        await message.reply_text("O'zingizni ban qila olmaysiz.")
        return
    try:
        target_member = await context.bot.get_chat_member(update.effective_chat.id, target.id)
        if target_member.status in ("administrator", "creator"):
            await message.reply_text("Administratorni bu buyruq bilan ban qilib bo'lmaydi.")
            return
        await context.bot.ban_chat_member(update.effective_chat.id, target.id)
        await message.reply_text(f"✅ {target.full_name} guruhdan chiqarildi.")
    except TelegramError:
        await message.reply_text("Ban bajarilmadi. Botda foydalanuvchini ban qilish huquqi borligini tekshiring.")


async def mute_replied_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not await require_group_admin(update, context):
        return
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if not target:
        await message.reply_text("Foydalanuvchining xabariga reply qilib /mute 10 yozing.")
        return
    try:
        minutes = int(context.args[0]) if context.args else 60
        if minutes < 1 or minutes > 10080:
            raise ValueError
    except ValueError:
        await message.reply_text("Daqiqa 1 dan 10080 gacha bo'lishi kerak. Misol: /mute 10")
        return
    if target.id == update.effective_user.id:
        await message.reply_text("O'zingizni cheklay olmaysiz.")
        return
    try:
        member = await context.bot.get_chat_member(update.effective_chat.id, target.id)
        if member.status in ("administrator", "creator"):
            await message.reply_text("Administratorni bu buyruq bilan cheklab bo'lmaydi.")
            return
        until_date = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            target.id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until_date,
        )
        await message.reply_text(f"✅ {target.full_name} {minutes} daqiqaga cheklab qo'yildi.")
    except TelegramError:
        await message.reply_text("Cheklash bajarilmadi. Botga foydalanuvchilarni cheklash huquqini bering.")


async def unmute_replied_user(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not await require_group_admin(update, context):
        return
    target = message.reply_to_message.from_user if message.reply_to_message else None
    if not target:
        await message.reply_text("Cheklovi olinadigan foydalanuvchining xabariga reply qilib /unmute yozing.")
        return
    try:
        await context.bot.restrict_chat_member(
            update.effective_chat.id,
            target.id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_audios=True,
                can_send_documents=True,
                can_send_photos=True,
                can_send_videos=True,
                can_send_video_notes=True,
                can_send_voice_notes=True,
                can_send_polls=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True,
            ),
        )
        await message.reply_text(f"✅ {target.full_name} uchun yozish cheklovi olib tashlandi.")
    except (TelegramError, TypeError):
        await message.reply_text("Cheklov olib tashlanmadi. Botning administrator huquqlarini tekshiring.")


async def post_to_channel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    if not update.effective_user:
        return
    args_text = " ".join(context.args).strip()
    if not args_text or " " not in args_text:
        await message.reply_text("Foydalanish: /post @kanal_username Matnli post")
        return
    channel, post_text = args_text.split(" ", 1)
    if not channel.startswith("@"):
        await message.reply_text("Kanalni @username ko'rinishida kiriting. Misol: /post @meningkanalim Salom!")
        return
    # Faqat kanal administratori post yuborishi mumkin.
    if not await is_chat_admin(update, context, channel):
        await message.reply_text("⛔ Siz bu kanalda administrator emassiz yoki kanalni tekshirib bo'lmadi.")
        return
    try:
        bot_member = await context.bot.get_chat_member(channel, context.bot.id)
        if bot_member.status not in ("administrator", "creator"):
            await message.reply_text("Avval botni kanalga administrator qilib qo'shing.")
            return
        await context.bot.send_message(chat_id=channel, text=post_text)
        await message.reply_text("✅ Post kanalga joylandi.")
    except TelegramError:
        await message.reply_text("Post joylanmadi. Kanal username'i va bot huquqlarini tekshiring.")


async def manage_with_ai(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Adminning tabiiy tildagi so'rovini xavfsiz tekshiradi; o'zboshimchalik bilan ban qilmaydi."""
    message = update.effective_message
    chat = update.effective_chat
    request = " ".join(context.args).strip()
    if not request and message.text:
        request = re.sub(r"^/manage(?:@\w+)?\s*", "", message.text, flags=re.IGNORECASE).strip()
    if not request:
        await message.reply_text(
            "Vazifani yozing. Masalan: /manage guruh qoidalarini yozib ber\n"
            "Foydalanuvchini cheklash/o'chirish uchun uning xabariga reply qiling."
        )
        return

    # Guruh boshqaruvi faqat guruh adminlariga. Shaxsiy chatda esa AI yordam beradi,
    # ammo guruh amallari uchun alohida guruhda adminlik tekshiriladi.
    if chat.type in ("group", "supergroup") and not await is_chat_admin(update, context):
        await message.reply_text("⛔ Guruhni boshqarish buyruqlarini faqat administrator ishlata oladi.")
        return

    target_user = message.reply_to_message.from_user if message.reply_to_message else None
    prompt = (
        "Foydalanuvchining Telegram guruh/kanal boshqaruv so'roviga o'zbekcha javob ber. "
        "Bu buyruq AI yordamchiga yuborildi. Agar foydalanuvchi qoidalar, e'lon yoki post matnini so'rasa, uni tayyorla. "
        "Agar real boshqaruv amali so'ralsa, aniq kerakli slash-buyruqni ko'rsat; hech qachon amal bajarildi deb yolg'on aytma. "
        "Foydalanuvchini ban/mute qilish, xabarni o'chirish va kanalga post yuborish uchun botda alohida buyruqlar mavjud.\n\n"
        f"So'rov: {request}\n"
        f"Reply qilingan foydalanuvchi: {target_user.full_name if target_user else 'yo‘q'}"
    )
    try:
        result = await generate(prompt)
        await send_long(message, result)
    except Exception:
        logger.exception("AI boshqaruv so'rovida xato")
        await message.reply_text("AI so'rovni bajara olmadi. API kaliti va limitini tekshiring.")


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

    # Guruh va kanal boshqaruvi uchun yangi buyruqlar
    app.add_handler(CommandHandler("grouphelp", management_help))
    app.add_handler(CommandHandler("del", delete_replied_message))
    app.add_handler(CommandHandler("ban", ban_replied_user))
    app.add_handler(CommandHandler("mute", mute_replied_user))
    app.add_handler(CommandHandler("unmute", unmute_replied_user))
    app.add_handler(CommandHandler("post", post_to_channel))
    app.add_handler(CommandHandler("manage", manage_with_ai))

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