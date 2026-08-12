import os
from telegram import Update, ChatPermissions
from telegram.ext import (
    Application,
    MessageHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)

TOKEN = os.environ["BOT_TOKEN"]

# Bu yerga taqiqlamoqchi bo'lgan so'zlarni yozing
TAQIQLANGAN = [
    "uyatsiz_soz",
    "uyatsiz_nik",
    "18plus",
]

async def tekshir_xabar(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.effective_message
    user = update.effective_user

    if not message or not user:
        return

    # Bot va adminlarni o'tkazib yuborish
    if user.is_bot:
        return

    try:
        member = await context.bot.get_chat_member(
            message.chat_id,
            user.id
        )

        if member.status in ("administrator", "creator"):
            return
    except Exception:
        pass

    username = (user.username or "").lower()
    first_name = (user.first_name or "").lower()
    last_name = (user.last_name or "").lower()
    text = (message.text or message.caption or "").lower()

    tekshiruv = f"{username} {first_name} {last_name} {text}"

    topildi = any(soz.lower() in tekshiruv for soz in TAQIQLANGAN)

    if not topildi:
        return

    try:
        # Xabarini o'chirish
        await message.delete()

        # Yozish huquqini cheklash
        await context.bot.restrict_chat_member(
            chat_id=message.chat_id,
            user_id=user.id,
            permissions=ChatPermissions(
                can_send_messages=False
            )
        )

        print(f"Cheklangan foydalanuvchi: {user.id}")

    except Exception as e:
        print("Xato:", e)



    if not member_update:
        return

    user = member_update.new_chat_member.user

    if user.is_bot:
        return

    username = (user.username or "").lower()
    first_name = (user.first_name or "").lower()
    last_name = (user.last_name or "").lower()

    tekshiruv = f"{username} {first_name} {last_name}"

    topildi = any(soz.lower() in tekshiruv for soz in TAQIQLANGAN)

    if not topildi:
        return

    try
