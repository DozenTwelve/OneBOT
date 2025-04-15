import os
import httpx
import re
import psutil

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-exp:free")
CURRENT_YEAR = "2025"

# ✅ 检测内存，超过限制自动退出

def check_memory_and_exit(limit_mb=900):
    mem = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
    if mem > limit_mb:
        print(f"⚠️ 内存超限：{mem:.2f} MB，准备退出")
        os._exit(0)

# ✅ 清洗输出，防止 markdown 裂开 + 修处时间

def sanitize_discord_output(text: str) -> str:
    text = text.replace("**", "** ").replace("__", "__ ").replace("*", "* ")
    text = text.strip()

    # ✅ 删除 AI 产生的开头说明
    text = re.sub(
        r"(?i)^(ok(ay)?|sure|alright)[\s,!.]*here.*?(?=\n|[-]{3,}|[A-Z]{2,})",
        "", text
    )
    text = re.sub(r"^[-\s\n]{2,}", "", text).strip()

    # ✅ 删除 disclaimer 或 footnote
    text = re.sub(r"(?i)disclaimer[:\uff1a\*].*", "", text, flags=re.DOTALL)
    text = re.sub(r"\*{1,2}\s*$", "", text).strip()

    # ✅ 修处过时 hashtag
    text = re.sub(r"#Trump20\d{2}", f"#Trump{CURRENT_YEAR}", text, flags=re.IGNORECASE)
    text = re.sub(r"#Biden20\d{2}", "", text, flags=re.IGNORECASE)

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
        f"You are Donald J. Trump. The current year is {CURRENT_YEAR}. "
        "You write short, sarcastic, bold, and funny Truth Social-style tweets. "
        "Use ALL CAPS, emojis, and phrases like 'SAD!', 'FAKE NEWS!', 'DISASTER!'. "
        "Only one tweet per response. Max 280 characters. Be aggressive and funny."
    )

    if not user:
        topic = topic or "the fake news media"
        user = f"Write a savage Truth Social post attacking {topic}. Be brutal, sarcastic, and entertaining like a real Trump post."

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
        async with httpx.AsyncClient() as client:
            res = await client.post("https://openrouter.ai/api/v1/chat/completions", headers=headers, json=data)
            res_data = res.json()

            if "error" in res_data:
                if res_data["error"].get("code") == 429:
                    return "🚫 太多人在用 TrumpBot！请等等再试～（模型限流）"
                return f"❌ 模型错误：{res_data['error'].get('message', '未知错误')}"

            content = extract_content(res_data)
            if not content or len(content) < 16:
                return "⚠️ 模型没有返回有效内容，或输出太短，请稍后再试。"

            # 输出前检测内存
            check_memory_and_exit()

            return sanitize_discord_output(content)

    except Exception as e:
        print("❌ AI 请求失败:", e)
        check_memory_and_exit()
        return "⚠️ AI 请求失败，请稍后再试。"