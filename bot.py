import os
import discord
from discord.ext import commands
import re
import asyncio
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()
TOKEN = os.getenv("DISCORD_BOT_TOKEN")

intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents)

async def get_trump_posts(count=1):
    """爬取特朗普 Truth Social 最新的帖子"""
    count = max(1, min(count, 5))  # 限制爬取数量在 1 到 5 条之间
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
        # 访问特朗普 Truth Social 页面
        url = "https://truthsocial.com/@realDonaldTrump"
        await page.goto(url, wait_until="domcontentloaded")  # ✅ 避免 "networkidle" 过于严格
        await page.wait_for_timeout(5000)  # 等待加载

        posts = []
        max_scrolls = 10  # 限制最多滚动 10 次
        scroll_count = 0

        while len(posts) < count and scroll_count < max_scrolls:
            post_elements = await page.locator("div.status__content-wrapper").all()
            print(f"🧐 找到 {len(post_elements)} 个帖子元素")  # ✅ 调试输出

            for post in post_elements:
                if len(posts) >= count:
                    break  # ✅ 确保不会爬取超过 `count` 条帖子

                text_elements = await post.locator("p.text-base").all()
                post_text = "\n".join([await t.inner_text() for t in text_elements])
                clean_text = re.sub(r'http\S+', '', post_text).strip()

                if clean_text and clean_text not in posts:
                    posts.append(clean_text)

            if len(posts) < count:
                await page.evaluate("window.scrollBy(0, 500)")  # ✅ 滚动加载更多帖子
                await asyncio.sleep(2)  # ✅ 等待加载
                scroll_count += 1

        await browser.close()

        if not posts:
            print("❌ 未找到帖子！可能是网站加载过慢，请重试！")  # ✅ 终端打印
            return ["❌ 未找到帖子！可能是网站加载过慢，请重试！"]  # ✅ 让 bot 发送消息

        print(f"✅ 实际爬取 {len(posts)} 条帖子")  # ✅ 输出结果
        return posts
    
@bot.event
async def on_ready():
    print(f"✅ {bot.user} 已上线！")

@bot.command()
async def trump(ctx, count: int = 1):
    """处理 /trump 命令，默认 1 条，支持 /trump 2 这种格式"""
    count = max(1, min(count, 5))  # 确保 count 在 1-5 之间
    print(f"📩 收到命令: /trump {count}")
    posts = await get_trump_posts(count)  # 确保 count 传递正确
    print(f"✅ 实际爬取 {len(posts)} 条帖子")  # **调试信息**
    for i, post in enumerate(posts, 1):
        await ctx.send(f"📢 **帖子 {i}**:\n{post}")

@bot.event
async def on_message(message):
    """处理 @机器人 的情况"""
    if message.author == bot.user:
        return  

    if bot.user.mentioned_in(message):
        print(f"📩 收到 @消息: {message.content}")

        match = re.search(r'\b([1-5])\b', message.content)
        count = int(match.group(1)) if match else 1
        count = max(1, min(count, 5))  

        print(f"✅ 解析 `@机器人 {count}` 请求 {count} 条帖子")
        
        posts = await get_trump_posts(count)
        for i, post in enumerate(posts, 1):
            await message.channel.send(f"📢 **帖子 {i}**:\n{post}")

    await bot.process_commands(message)  

bot.run(TOKEN)