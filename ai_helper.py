import os
import httpx
import re

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
MODEL = os.getenv("OPENROUTER_MODEL", "google/gemini-2.0-flash-exp:free")
CURRENT_YEAR = "2025"

# ✅ 清洗输出，防止 markdown 裂开

def sanitize_discord_output(text: str) -> str:
    # 初步清洗 markdown
    text = text.replace("**", "** ").replace("__", "__ ").replace("*", "* ")
    text = text.strip()

    # ✅ 清除开头的 "OKAY, HERE'S..."、"Sure, here's..." 等非正文
    text = re.sub(
        r"(?i)^(ok(ay)?|sure|alright)[\s,!\.]*here.*?(?=\n|[-]{3,}|[A-Z]{2,})",  # 保证保留大写句子正文
        "", text
    )

    # ✅ 清除前置 "---" 或换行符号
    text = re.sub(r"^[-–—\s\n]{2,}", "", text).strip()

    # ✅ 清除末尾 disclaimer 或 "* *" 脚注
    text = re.sub(r"(?i)disclaimer[:：\*].*", "", text, flags=re.DOTALL)
    text = re.sub(r"\*{1,2}\s*$", "", text).strip()

    text = re.sub(r"#Trump2024", f"#Trump{CURRENT_YEAR}", text, flags=re.IGNORECASE)

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

    # ✅ 默认 Trump 风格 System Prompt
    system = system or (
        "You are Donald J. Trump. You write short, sarcastic, bold, and funny Truth Social-style tweets. "
        "Use ALL CAPS, emojis, and phrases like 'SAD!', 'FAKE NEWS!', 'DISASTER!'. "
        "Only one tweet per response. Max 280 characters. Be aggressive and funny."
    )

    # ✅ 默认用户 Prompt（带 topic）
    user = user or f"Write a savage Truth Social post attacking {topic}. Be brutal, sarcastic, and entertaining like a real Trump post."
    if not user:
        topic = topic or "the fake news media"
        user = f"Write a savage Truth Social post attacking {topic}."


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

            # ✅ 错误检测（如限流）
            if "error" in res_data:
                if res_data["error"].get("code") == 429:
                    return "🚫 太多人在用 TrumpBot！请稍等几秒再试～（模型限流）"
                return f"❌ 模型错误：{res_data['error'].get('message', '未知错误')}"

            # ✅ 正常提取 & 校验内容
            content = extract_content(res_data)
            if not content or len(content) < 16:
                return "⚠️ 模型没有返回有效内容，或输出太短，请稍后再试。"

            return sanitize_discord_output(content)

    except Exception as e:
        print("❌ AI 请求失败:", e)
        return "⚠️ AI 请求失败，请稍后再试。"
