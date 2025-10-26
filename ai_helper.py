import logging
import os
import re

import httpx
import psutil
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-3-12b-it:free")
CURRENT_YEAR = "2025"
APP_MEMORY_LIMIT_MB = int(os.getenv("APP_MEMORY_LIMIT_MB", "900"))

logger = logging.getLogger("trumpbot.ai")

# ✅ 检测内存，超过限制自动退出

def check_memory_and_exit(limit_mb: int = APP_MEMORY_LIMIT_MB) -> None:
    mem = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
    if mem > limit_mb:
        logger.error("Memory limit exceeded: %.2f MB > %s MB. Exiting process.", mem, limit_mb)
        os._exit(0)
    logger.debug("Memory usage check passed: %.2f MB (limit %s MB).", mem, limit_mb)

# ✅ 清洗输出，防止 markdown 裂开 + 修处时间

def sanitize_discord_output(text: str) -> str:
    text = text.replace("**", "** ").replace("__", "__ ").replace("*", "* ")
    text = text.strip()

    # ✅ 删除 AI 产生的开头说明
    text = re.sub(r"^[-\s\n]{2,}", "", text).strip()
    text = re.sub(
        r"(?i)^(respond with|okay|sure)[^\n]*?(post|style)[^\n]*\n?", "", text
    )

    # ✅ 删除 disclaimer 或 footnote
    text = re.sub(r"(?i)disclaimer[:\uff1a\*].*", "", text, flags=re.DOTALL)
    text = re.sub(r"\*{1,2}\s*$", "", text).strip()
    text = re.sub(r">", "\n", text)   
    text = re.sub(r"^[\s\n]+", "", text)
    text = re.sub(r"\*{1,2}\s*$", "", text)

    # ✅ 修处过时 hashtag
    text = re.sub(r"#Trump20\d{2}", f"#Trump{CURRENT_YEAR}", text, flags=re.IGNORECASE)
    text = re.sub(r"#Biden20\d{2}", "", text, flags=re.IGNORECASE)

    text = re.sub(
        r"(?i)(---+|IMPORTANT.*|This is a fictional exercise.*|The content is offensive.*)",
        "", text, flags=re.DOTALL
    )

    return text.strip()

# ✅ 提取模型返回内容（支持 GPT / Gemini 等）
def extract_content(data):
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, TypeError):
        try:
            return data["choices"][0].get("content", "").strip()
        except Exception:
            return ""

# ✅ 主函数：生成 AI 回复
async def ask_ai(topic="", system="", user=""):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://yourdomain.com",
        "X-Title": "TrumpBot"
    }

    # ✅ 默认 system prompt 加入当前年份
    system = system or (
        f"You are a stand-up comedian impersonating Donald Trump in {CURRENT_YEAR}. "
        "You ONLY write short, sarcastic, bold, and funny Truth Social-style tweets. "
        "Use ALL CAPS, emojis, and phrases like 'SAD!', 'FAKE NEWS!', 'DISASTER!'. "
        "Respond with ONLY ONE tweet. Do NOT explain, do NOT clarify, and absolutely NO disclaimers. "
        "Just the tweet. Nothing else. Your tweet MUST end with a period ('.') and contain no follow-up explanation. "
        "If you are not allowed to respond due to content moderation, respond IN CHARACTER as Trump yelling at the user for being TOO SENSITIVE or for CENSORSHIP."
        "Maximum 280 characters."
    )

    if not user:
        topic = topic or "the fake news media"
        user = f"Write a Truth Social post about {topic}."

    data = {
        "model": MODEL,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user}
        ],
        "temperature": 0.9,
        "top_p": 0.9,
        "max_tokens": 256
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)
            res_data = res.json()

            if "error" in res_data:
                if res_data["error"].get("code") == 429:
                    logger.warning("OpenRouter rate limited the request.")
                    return "🚫 太多人在用 TrumpBot！请等等再试～（模型限流）"
                message = res_data["error"].get("message", "未知错误")
                logger.error("Model returned an error: %s", message)
                return f"❌ 模型错误：{message}"

            content = extract_content(res_data)
            if not content or len(content) < 16:
                logger.warning("Model returned empty or too-short content.")
                return "⚠️ 模型没有返回有效内容，或输出太短，请稍后再试。"

            # 输出前检测内存
            check_memory_and_exit(limit_mb=APP_MEMORY_LIMIT_MB)

            return sanitize_discord_output(content)

    except Exception as e:  # noqa: BLE001
        logger.exception("AI request failed: %s", e)
        check_memory_and_exit(limit_mb=APP_MEMORY_LIMIT_MB)
        return "⚠️ AI 请求失败，请稍后再试。"
