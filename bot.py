import os
import discord
from discord.ext import commands
import re
import asyncio
import httpx
from dotenv import load_dotenv
from playwright.async_api import async_playwright

# 读取环境变量
load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

# 配置 Discord 机器人
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

# ✅ 爬取 Trump Truth Social 帖子
async def get_trump_posts(count=1):
    count = max(1, min(count, 5))
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"]
        )
        context = await browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = await context.new_page()

        print(f"🔍 访问特朗普 Truth Social 页面... 需要获取 {count} 条帖子")
        await page.goto("https://truthsocial.com/@realDonaldTrump", wait_until="domcontentloaded")
        await page.wait_for_timeout(5000)

        posts = []
        max_scrolls = 10
        scroll_count = 0

        while len(posts) < count and scroll_count < max_scrolls:
            post_elements = await page.locator("div.status__content-wrapper").all()
            print(f"🧐 找到 {len(post_elements)} 个帖子元素")
            for post in post_elements:
                if len(posts) >= count:
                    break
                text_elements = await post.locator("p.text-base").all()
                post_text = "\n".join([await t.inner_text() for t in text_elements])
                clean_text = re.sub(r'http\S+', '', post_text).strip()
                if clean_text and clean_text not in posts:
                    posts.append(clean_text)
            if len(posts) < count:
                await page.evaluate("window.scrollBy(0, 500)")
                await asyncio.sleep(2)
                scroll_count += 1

        await browser.close()

        if not posts:
            print("❌ 未找到帖子！可能是网站加载过慢，请重试！")
            return ["❌ 未找到帖子！可能是网站加载过慢，请重试！"]

        print(f"✅ 实际爬取 {len(posts)} 条帖子")
        return posts

# ✅ 使用 OpenRouter 生成 Trump 风格的笑话
async def ask_trump_joke(topic=""):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://yourdomain.com",
        "X-Title": "Trump Joke Generator"
    }

    data = {
        "model": "google/gemini-2.5-pro-exp-03-25:free",  # 或其他支持的模型
        "messages": [
            {
                "role": "system",
                "content": "You are Donald Trump. Write short, bold, sarcastic, tweet-style jokes or insults. Be funny, exaggerate, and act like you're on Twitter. Use all-caps and emojis if needed."
            },
            {
                "role": "user",
                "content": f"Make a funny tweet about {topic or 'fake news'}"
            }
        ],
        "temperature": 0.9,
        "top_p": 0.9,
        "max_tokens": 256
    }

    try:
        async with httpx.AsyncClient() as client:
            res = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=data
            )

            raw_text = await res.aread()

            if res.status_code != 200:
                print("❌ OpenRouter API 错误状态码:", res.status_code)
                print("🔍 返回内容:", raw_text.decode())
                return f"⚠️ API 错误 {res.status_code}"

            try:
                res_data = res.json()
            except Exception as e:
                print("❌ JSON 解析失败:", e)
                print("🔍 原始内容:", raw_text.decode())
                return "⚠️ 无法解析 OpenRouter 的响应，请稍后再试"

            if "choices" not in res_data or not res_data["choices"]:
                print("❌ 返回中缺少 'choices'")
                print("🧾 完整响应:", res_data)
                return "⚠️ OpenRouter 没有返回有效内容，请稍后再试！"

            return res_data["choices"][0]["message"]["content"].strip()

    except Exception as e:
        print("❌ OpenRouter 异常:", e)
        return "⚠️ OpenRouter 请求失败，请稍后再试！"

# ✅ 机器人上线提示
@bot.event
async def on_ready():
    print(f"✅ {bot.user} 已上线！")

# ✅ /trump 命令：抓取帖子
@bot.command()
async def trump(ctx, count: int = 1):
    count = max(1, min(count, 5))
    print(f"📩 收到命令: /trump {count}")
    posts = await get_trump_posts(count)
    for i, post in enumerate(posts, 1):
        await ctx.send(f"📢 **帖子 {i}**:\n{post}")

# ✅ /trumpjoke 命令：生成笑话
@bot.command()
async def trumpjoke(ctx, *, topic: str = ""):
    print(f"📩 收到命令: /trumpjoke {topic}")
    joke = await ask_trump_joke(topic)
    await ctx.send(f"🧠 **Trump 风格笑话**:\n{joke}")

# ✅ @机器人时处理
@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if bot.user.mentioned_in(message):
        content_lower = message.content.lower()
        print(f"📩 收到 @消息: {message.content}")

        if "help" in content_lower:
            help_prompt = """
As Donald Trump, write a short and funny help message for a Discord bot.
Describe the available commands in an overconfident, sarcastic tone.
Use caps, exaggeration, emojis, and act like you're the greatest president AND bot creator.
Commands:
- /trump [1~5]: Get the latest Trump posts
- /trumpjoke [topic]: Generate a Trump-style tweet joke
- @Bot joke: Ask the bot to tell a joke
- @Bot 3: Get 3 latest posts
- @Bot help: Show this amazing help
"""
            help_text = await ask_trump_joke(help_prompt)
            await message.channel.send(f"📢 **TrumpBot Help**:\n{help_text}")
            return


        if "joke" in content_lower:
            joke = await ask_trump_joke()
            await message.channel.send(f"🧠 **Trump 风格笑话**:\n{joke}")
            return

        match = re.search(r'\b([1-5])\b', message.content)
        count = int(match.group(1)) if match else 1
        count = max(1, min(count, 5))
        print(f"✅ 解析 @请求 {count} 条帖子")
        posts = await get_trump_posts(count)
        for i, post in enumerate(posts, 1):
            await message.channel.send(f"📢 **帖子 {i}**:\n{post}")

    await bot.process_commands(message)

# ✅ 启动机器人
bot.run(TOKEN)