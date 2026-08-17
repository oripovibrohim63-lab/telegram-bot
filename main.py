import os
import re
import urllib.parse
import requests

from google import genai
from google.genai import types

from telegram import Update, ChatPermissions
from telegram.ext import (
    Application,
    MessageHandler,
    ChatMemberHandler,
    ContextTypes,
    filters,
)

# =========================================================
# SOZLAMALAR
# =========================================================

TOKEN = os.environ["BOT_TOKEN"]
GEMINI_API_KEY = os.environ["GEMINI_API_KEY"]

# Gemini
gemini_client = genai.Client(api_key=GEMINI_API_KEY)

GEMINI_MODEL = "gemini-3.6-flash"

# Taqiqlangan so'zlar
TAQIQLANGAN = [
    "uyatsiz_soz",
    "uyatsiz_nik",
    "18plus",
]

# AI javob berishi kerak bo'lgan savollar
# True bo'lsa AI ishlaydi
AI_CHAT_ENABLED = True


# =========================================================
# GEMINI SISTEMA KO'RSATMASI
# =========================================================

AI_SYSTEM = """
Sen Telegram guruhidagi yordamchi botsan.

Vazifang:
- O'zbek tilida tabiiy gaplash.
- Foydalanuvchi bilan do'stona va qisqa suhbat qil.
- Savolga tushunarli javob ber.
- Keraksiz uzun javob yozma.
- Foydalanuvchi hazillashsa, mos ravishda javob ber.
- "salom", "nima gap", "qandaysiz", "nima qilyapsan"
  kabi oddiy suhbatlarni tabiiy davom ettir.
- O'zingni AI yordamchi ekaningni yashirma.
- Bilmagan narsangni uydirma.
- Foydalanuvchi o'zbekcha yozsa o'zbekcha javob ber.
- Ruscha yozsa ruscha javob ber.
- Inglizcha yozsa inglizcha javob ber.

Javoblar odatda 1-5 ta qisqa gapdan iborat bo'lsin.
"""


# =========================================================
# ADMIN TEKSHIRISH
# =========================================================

async def adminmi(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
) -> bool:

    message = update.effective_message
    user = update.effective_user

    if not message or not user:
        return False

    try:
        member = await context.bot.get_chat_member(
            chat_id=message.chat_id,
            user_id=user.id
        )

        return member.status in (
            "administrator",
            "creator"
        )

    except Exception as e:
        print("Admin tekshirish xatosi:", e)
        return False


# =========================================================
# TAQIQLANGAN SO'ZNI TEKSHIRISH
# =========================================================

def taqiqlangan_topildimi(text: str) -> bool:

    text = text.lower()

    return any(
        soz.lower() in text
        for soz in TAQIQLANGAN
    )


# =========================================================
# USER MA'LUMOTLARINI TEKSHIRISH
# =========================================================

def foydalanuvchini_tekshir(user) -> bool:

    username = (user.username or "").lower()
    first_name = (user.first_name or "").lower()
    last_name = (user.last_name or "").lower()

    tekshiruv = (
        f"{username} "
        f"{first_name} "
        f"{last_name}"
    )

    return taqiqlangan_topildimi(tekshiruv)


# =========================================================
# USERNI MUTE QILISH
# =========================================================

async def mute_user(
    chat_id,
    user_id,
    context
):

    await context.bot.restrict_chat_member(
        chat_id=chat_id,
        user_id=user_id,
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


# =========================================================
# XABARNI MODERATSIYA QILISH
# =========================================================

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

        # Userni mute qilish
        await mute_user(
            message.chat_id,
            user.id,
            context
        )

        print(
            f"Foydalanuvchi mute qilindi: "
            f"{user.id} | @{user.username}"
        )

    except Exception as e:

        print(
            "Moderatsiya xatosi:",
            e
        )


# =========================================================
# YANGI USERNI TEKSHIRISH
# =========================================================

async def yangi_foydalanuvchini_tekshir(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    member_update = update.chat_member

    if not member_update:
        return

    user = member_update.new_chat_member.user

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

        await mute_user(
            member_update.chat.id,
            user.id,
            context
        )

        print(
            f"Yangi user mute qilindi: "
            f"{user.id} | @{user.username}"
        )

    except Exception as e:

        print(
            "Yangi user mute xatosi:",
            e
        )


# =========================================================
# WIKIPEDIA QIDIRUV
# =========================================================

def wikipedia_qidiruv(
    sorov: str
):

    try:

        url = "https://en.wikipedia.org/w/api.php"

        params = {
            "action": "query",
            "format": "json",
            "list": "search",
            "srsearch": sorov,
            "srlimit": 1,
        }

        response = requests.get(
            url,
            params=params,
            timeout=10
        )

        data = response.json()

        results = (
            data
            .get("query", {})
            .get("search", [])
        )

        if not results:
            return None

        title = results[0]["title"]

        summary_url = (
            "https://en.wikipedia.org/api/rest_v1/page/summary/"
            + urllib.parse.quote(
                title.replace(" ", "_")
            )
        )

        summary_response = requests.get(
            summary_url,
            timeout=10
        )

        summary_data = (
            summary_response.json()
        )

        return {
            "title": title,
            "description": summary_data.get(
                "extract",
                ""
            ),
            "url": (
                summary_data
                .get("content_urls", {})
                .get("desktop", {})
                .get("page", "")
            )
        }

    except Exception as e:

        print(
            "Wikipedia xatosi:",
            e
        )

        return None


# =========================================================
# WIKIMEDIA RASM QIDIRISH
# =========================================================

def rasm_qidiruv(
    sorov: str
):

    try:

        url = (
            "https://commons.wikimedia.org/"
            "w/api.php"
        )

        params = {
            "action": "query",
            "format": "json",
            "generator": "search",
            "gsrsearch": sorov,
            "gsrnamespace": 6,
            "gsrlimit": 5,
            "prop": "imageinfo",
            "iiprop": "url",
        }

        response = requests.get(
            url,
            params=params,
            timeout=15
        )

        data = response.json()

        pages = (
            data
            .get("query", {})
            .get("pages", {})
        )

        for page in pages.values():

            imageinfo = page.get(
                "imageinfo",
                []
            )

            if not imageinfo:
                continue

            image_url = imageinfo[0].get(
                "url"
            )

            if image_url:
                return image_url

        return None

    except Exception as e:

        print(
            "Rasm qidirish xatosi:",
            e
        )

        return None


# =========================================================
# RASM SO'ROVINI ANIQLASH
# =========================================================

def rasm_sorovini_ol(
    text: str
):

    text = text.strip()

    patterns = [

        r"^(.*?)\s+rasmini\s+top$",

        r"^(.*?)\s+rasmini\s+yubor$",

        r"^(.*?)\s+rasm\s+top$",

        r"^(.*?)\s+rasm\s+kerak$",

        r"^rasm\s+top\s+(.*?)$",

        r"^rasmini\s+top\s+(.*?)$",

        r"^rasm\s+yubor\s+(.*?)$",

        r"^menga\s+(.*?)\s+rasmini\s+top$",

        r"^menga\s+(.*?)\s+rasmini\s+yubor$",
    ]

    for pattern in patterns:

        match = re.match(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            return match.group(
                1
            ).strip()

    return None


# =========================================================
# SO'Z QIDIRUV SO'ROVINI ANIQLASH
# =========================================================

def soz_sorovini_ol(
    text: str
):

    text = text.strip()

    patterns = [

        r"^(.*?)\s+kim$",

        r"^(.*?)\s+haqida\s+ayt$",

        r"^(.*?)\s+haqida\s+ma'?lumot$",

        r"^kim\s+bu\s+(.*?)$",

        r"^bu\s+kim\s+(.*?)$",

        r"^qidir\s+(.*?)$",

        r"^top\s+(.*?)$",
    ]

    for pattern in patterns:

        match = re.match(
            pattern,
            text,
            re.IGNORECASE
        )

        if match:

            return match.group(
                1
            ).strip()

    return None


# =========================================================
# GEMINI AI JAVOB
# =========================================================

async def gemini_javob(
    text: str
):

    try:

        response = (
            gemini_client
            .models
            .generate_content(
                model=GEMINI_MODEL,
                contents=text,
                config=types.GenerateContentConfig(
                    system_instruction=AI_SYSTEM,
                    temperature=0.8,
                    max_output_tokens=500,
                ),
            )
        )

        answer = response.text

        if not answer:
            return None

        return answer.strip()

    except Exception as e:

        print(
            "Gemini xatosi:",
            e
        )

        return None


# =========================================================
# AI KERAKLIGINI ANIQLASH
# =========================================================

def ai_savolmi(
    text: str
) -> bool:

    text = text.strip().lower()

    # Juda qisqa oddiy so'zlarni AI'ga yubormaymiz
    oddiy_gaplar = {
        "salom",
        "assalom",
        "assalomu alaykum",
        "rahmat",
        "xayr",
        "hayr",
        "qandaysiz",
        "yaxshi",
        "ha",
        "yo'q",
        "yoq",
        "mayli",
        "bo'pti",
        "boladi",
        "bo'ladi",
    }

    if text in oddiy_gaplar:
        return True

    # Savol belgilari
    if "?" in text:
        return True

    # AI bilan suhbatga o'xshash gaplar
    kalitlar = [
        "nima",
        "nega",
        "qanday",
        "qachon",
        "qayerda",
        "kim",
        "ayt",
        "tushuntir",
        "fikring",
        "o'ylaysan",
        "maslahat",
        "yordam",
        "gaplash",
        "zerik",
        "zerikdim",
        "nima qilyapsan",
        "nima gap",
    ]

    return any(
        kalit in text
        for kalit in kalitlar
    )


# =========================================================
# AVTOMATIK JAVOB + QIDIRUV + AI
# =========================================================

async def reply_message(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    message = update.message

    if not message or not message.text:
        return

    text = message.text.strip()
    lower_text = text.lower()

    # =====================================================
    # TAQIQLANGAN SO'Z
    # =====================================================

    if taqiqlangan_topildimi(
        lower_text
    ):

        try:

            await message.delete()

        except Exception as e:

            print(
                "Xabarni o'chirish xatosi:",
                e
            )

        return

    # =====================================================
    # RASM QIDIRISH
    # =====================================================

    rasm_sorovi = rasm_sorovini_ol(
        lower_text
    )

    if rasm_sorovi:

        await message.reply_text(
            f"🔎 {rasm_sorovi} rasmi "
            f"qidirilmoqda..."
        )

        image_url = rasm_qidiruv(
            rasm_sorovi
        )

        if image_url:

            try:

                await message.reply_photo(
                    photo=image_url,
                    caption=(
                        f"🖼️ {rasm_sorovi}"
                    )
                )

            except Exception as e:

                print(
                    "Rasm yuborish xatosi:",
                    e
                )

                await message.reply_text(
                    "❌ Rasmni yuborishda "
                    "xatolik bo'ldi."
                )

        else:

            await message.reply_text(
                "❌ Bu nom bo'yicha "
                "rasm topilmadi."
            )

        return

    # =====================================================
    # WIKIPEDIA QIDIRISH
    # =====================================================

    soz_sorovi = soz_sorovini_ol(
        lower_text
    )

    if soz_sorovi:

        await message.reply_text(
            f"🔎 «{soz_sorovi}» "
            f"qidirilmoqda..."
        )

        result = wikipedia_qidiruv(
            soz_sorovi
        )

        if result:

            description = result[
                "description"
            ]

            if len(description) > 1500:

                description = (
                    description[:1500]
                    + "..."
                )

            javob = (
                f"📚 {result['title']}\n\n"
                f"{description}"
            )

            if result["url"]:

                javob += (
                    f"\n\n🔗 {result['url']}"
                )

            await message.reply_text(
                javob,
                disable_web_page_preview=True
            )

        else:

            await message.reply_text(
                "❌ Ma'lumot topilmadi."
            )

        return

    # =====================================================
    # ODDIY JAVOBLAR
    # =====================================================

    if lower_text == "salom":

        await message.reply_text(
            "Vaalaykum assalom! 👋\n"
            "Qanday yordam bera olaman?"
        )

        return

    if lower_text == "qandaysiz":

        await message.reply_text(
            "Rahmat, yaxshiman! 😊"
        )

        return

    if lower_text in (
        "assalomu alaykum",
        "assalom",
    ):

        await message.reply_text(
            "Vaalaykum assalom! 👋"
        )

        return

    if lower_text == "rahmat":

        await message.reply_text(
            "Arzimaydi! 😊"
        )

        return

    if lower_text in (
        "xayr",
        "hayr",
    ):

        await message.reply_text(
            "Xayr! 👋"
        )

        return

    # =====================================================
    # GEMINI AI
    # =====================================================

    if AI_CHAT_ENABLED:

        if ai_savolmi(
            lower_text
        ):

            await message.chat.send_action(
                action="typing"
            )

            answer = await gemini_javob(
                text
            )

            if answer:

                # Telegram xabar uzunligi
                # juda katta bo'lsa bo'lib yuborish
                if len(answer) <= 4000:

                    await message.reply_text(
                        answer
                    )

                else:

                    for i in range(
                        0,
                        len(answer),
                        4000
                    ):

                        await message.reply_text(
                            answer[i:i + 4000]
                        )

            else:

                await message.reply_text(
                    "❌ AI javob bera olmadi. "
                    "Birozdan keyin yana urinib ko'ring."
                )


# =========================================================
# BOTNI ISHGA TUSHIRISH
# =========================================================

def main():

    if not TOKEN:

        raise ValueError(
            "BOT_TOKEN topilmadi!"
        )

    if not GEMINI_API_KEY:

        raise ValueError(
            "GEMINI_API_KEY topilmadi!"
        )

    app = (
        Application
        .builder()
        .token(TOKEN)
        .build()
    )

    # =====================================================
    # 1. MODERATSIYA
    # =====================================================

    app.add_handler(
        MessageHandler(
            filters.ALL & ~filters.COMMAND,
            tekshir_xabar
        ),
        group=0
    )

    # =====================================================
    # 2. AVTOMATIK JAVOB + QIDIRUV + AI
    # =====================================================

    app.add_handler(
        MessageHandler(
            filters.TEXT & ~filters.COMMAND,
            reply_message
        ),
        group=1
    )

    # =====================================================
    # 3. YANGI USERNI TEKSHIRISH
    # =====================================================

    app.add_handler(
        ChatMemberHandler(
            yangi_foydalanuvchini_tekshir,
            ChatMemberHandler.CHAT_MEMBER
        )
    )

    print(
        "🤖 Telegram bot ishga tushdi..."
    )

    app.run_polling(
        allowed_updates=Update.ALL_TYPES
    )


# =========================================================
# START
# =========================================================

if __name__ == "__main__":
    main()
