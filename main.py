
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
