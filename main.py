import os

from telegram import Update, ChatPermissions
from telegram.ext import (
    Application,
    MessageHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)

# =========================
# SOZLAMALAR
# =========================

TOKEN = os.environ["BOT_TOKEN"]

# Taqiqlangan so'zlar
TAQIQLANGAN = [
    "uyatsiz_soz",
    "uyatsiz_nik",
    "18plus",
]


# =========================
# ADMIN TEKSHIRISH
# =========================

async def adminmi(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Foydalanuvchi guruh administratori yoki yaratuvchimi?"""

    message = update.effective_message
    user = update.effective_user

    if not message or not user:
        return False

    try:
        member = await context.bot.get_chat_member(
            chat_id=message.chat_id,
            user_id=user.id
        )

        return member.status in ("administrator", "creator")

    except Exception as e:
        print("Admin tekshirish xatosi:", e)
        return False


# =========================
# TAQIQLANGAN SO'ZNI TEKSHIRISH
# =========================

def taqiqlangan_topildimi(text: str) -> bool:
    """Matnda taqiqlangan so'z borligini tekshiradi."""

    text = text.lower()

    return any(
        soz.lower() in text
        for soz in TAQIQLANGAN
    )


# =========================
# FOYDALANUVCHI MA'LUMOTLARI
# =========================

def foydalanuvchini_tekshir(user) -> bool:
    """Username, ism va familiyani tekshiradi."""

    username = (user.username or "").lower()
    first_name = (user.first_name or "").lower()
    last_name = (user.last_name or "").lower()

    tekshiruv = f"{username} {first_name} {last_name}"

    return taqiqlangan_topildimi(tekshiruv)


# =========================
# XABARNI TEKSHIRISH
# =========================

async def tekshir_xabar(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.effective_message
    user = update.effective_user

    if not message or not user:
        return

    # Botlarni o'tkazib yuborish
    if user.is_bot:
        return

    # Adminlarni o'tkazib yuborish
    if await adminmi(update, context):
        return

    username = (user.username or "").lower()
    first_name = (user.first_name or "").lower()
    last_name = (user.last_name or "").lower()

    text = (
        message.text
        or message.caption
        or ""
    ).lower()

    # Username + ism + familiya + xabarni birgalikda tekshirish
    tekshiruv = (
        f"{username} "
        f"{first_name} "
        f"{last_name} "
        f"{text}"
    )

    if not taqiqlangan_topildimi(tekshiruv):
        return

    try:
        # Xabarni o'chirish
        await message.delete()

        # Foydalanuvchini mute qilish
        await context.bot.restrict_chat_member(
            chat_id=message.chat_id,
            user_id=user.id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_audios=False,
                can_send_documents=False,
                can_send_photos=False,
                can_send_videos=False,
                can_send_video_notes=False,
                can_send_voice_notes=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
            )
        )

        print(
            f"Foydalanuvchi mute qilindi: "
            f"{user.id} | @{user.username}"
        )

    except Exception as e:
        print("Moderatsiya xatosi:", e)


# =========================
# YANGI KIRGAN FOYDALANUVCHINI TEKSHIRISH
# =========================

async def yangi_foydalanuvchini_tekshir(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    member_update = update.chat_member

    if not member_update:
        return

    user = member_update.new_chat_member.user

    # Botlarni o'tkazib yuborish
    if user.is_bot:
        return

    username = (user.username or "").lower()
    first_name = (user.first_name or "").lower()
    last_name = (user.last_name or "").lower()

    tekshiruv = (
        f"{username} "
        f"{first_name} "
        f"{last_name}"
    )

    if not taqiqlangan_topildimi(tekshiruv):
        return

    try:
        await context.bot.restrict_chat_member(
            chat_id=member_update.chat.id,
            user_id=user.id,
            permissions=ChatPermissions(
                can_send_messages=False,
                can_send_audios=False,
                can_send_documents=False,
                can_send_photos=False,
                can_send_videos=False,
                can_send_video_notes=False,
                can_send_voice_notes=False,
                can_send_polls=False,
                can_send_other_messages=False,
                can_add_web_page_previews=False,
            )
        )

        print(
            f"Yangi foydalanuvchi mute qilindi: "
            f"{user.id} | @{user.username}"
        )

    except Exception as e:
        print("Yangi foydalanuvchini mute qilish xatosi:", e)


# =========================
# AVTOMATIK JAVOB
# =========================

async def reply_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):
    message = update.message

    if not message or not message.text:
        return

    text = message.text.strip().lower()

    # Taqiqlangan so'z bo'lsa xabarni o'chirish
    if taqiqlangan_topildimi(text):
        try:
            await message.delete()
        except Exception as e:
            print("Xabarni o'chirish xatosi:", e)

        return

    # Salom
    if text == "salom":
        await message.reply_text(
            "Vaalaykum assalom! 👋\n"
            "Qanday yordam bera olaman?"
        )

    # Qandaysiz
    elif text == "qandaysiz":
        await message.reply_text(
            "Rahmat, yaxshiman! 😊"
        )

    # Assalomu alaykum
    elif text in (
        "assalomu alaykum",
        "assalom",
    ):
        await message.reply_text(
            "Vaalaykum assalom! 👋"
        )

    # Rahmat
    elif text == "rahmat":
        await message.reply_text(
            "Arzimaydi! 😊"
        )

    # Xayr
    elif text in (
        "xayr",
        "hayr",
    ):
        await message.reply_text(
            "Xayr! 👋"
        )


# =========================
# BOTNI ISHGA TUSHIRISH
# =========================

def main():

    if not TOKEN:
        raise ValueError(
            "BOT_TOKEN topilmadi!"
        )

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    # 1. Guruhdagi xabarlarni moderatsiya qilish
    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            tekshir_xabar
        ),
        group=0
    )

    # 2. Avtomatik javoblar
    app.add_handler(
        MessageHandler(
            filters.TEXT
            & ~filters.COMMAND,
            reply_message
        ),
        group=1
    )

    # 3. Guruhga yangi kirgan foydalanuvchilarni tekshirish
    app.add_handler(
        ChatMemberHandler(
            yangi_foydalanuvchini_tekshir,
            ChatMemberHandler.CHAT_MEMBER
        )
    )

    print("🤖 Bot ishga tushdi...")

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


if __name__ == "__main__":
    main()
```
