import asyncio
import logging
import os
import re
from typing import List

import discord
import httpx
import psutil
from discord.ext import commands, tasks
from dotenv import load_dotenv
from playwright.async_api import async_playwright

load_dotenv()

TOKEN = os.getenv("DISCORD_BOT_TOKEN")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
APP_MEMORY_LIMIT_MB = int(os.getenv("APP_MEMORY_LIMIT_MB", "1900"))
POST_FETCH_RETRIES = max(1, int(os.getenv("TRUMPBOT_FETCH_RETRIES", "3")))
POST_FETCH_RETRY_DELAY = max(1, int(os.getenv("TRUMPBOT_FETCH_RETRY_DELAY", "5")))
STARTUP_RETRY_LIMIT = int(os.getenv("TRUMPBOT_STARTUP_RETRIES", "5"))
STARTUP_RETRY_DELAY = max(1, int(os.getenv("TRUMPBOT_STARTUP_RETRY_DELAY", "10")))
FREE_MODEL_REFRESH_HOURS = max(1, int(os.getenv("OPENROUTER_FREE_MODEL_REFRESH_HOURS", "168")))

logging.basicConfig(
    level=LOG_LEVEL,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("trumpbot")

from ai_helper import (  # noqa: E402
    ask_ai,
    check_memory_and_exit,
    get_current_model,
    refresh_free_models,
)

intents = discord.Intents.none()
intents.guilds = True
intents.messages = True
intents.message_content = True
bot = commands.Bot(command_prefix="/", intents=intents, max_messages=100)


async def ensure_dependencies_ready(max_attempts: int = 5, base_delay: int = 5) -> None:
    """Wait for critical external dependencies before starting the bot."""
    target_url = "https://truthsocial.com/@realDonaldTrump"
    for attempt in range(1, max_attempts + 1):
        try:
            async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
                response = await client.get(target_url)
                response.raise_for_status()
            logger.info("Dependency check succeeded against Truth Social.")
            return
        except Exception as exc:  # noqa: BLE001
            wait_time = base_delay * attempt
            logger.warning(
                "Dependency check attempt %s failed: %s. Retrying in %s seconds.",
                attempt,
                exc,
                wait_time,
            )
            if attempt == max_attempts:
                raise
            await asyncio.sleep(wait_time)


@tasks.loop(minutes=15)
async def clear_message_cache() -> None:
    """Periodically clear the cached message deque to reduce memory pressure."""
    removed = len(bot.cached_messages)
    bot.cached_messages.clear()
    logger.debug("Cleared cached Discord messages (removed %s).", removed)


@clear_message_cache.before_loop
async def before_clear_message_cache() -> None:
    await bot.wait_until_ready()


@tasks.loop(minutes=5)
async def report_resource_usage() -> None:
    """Emit periodic resource usage metrics for monitoring."""
    process = psutil.Process(os.getpid())
    memory_usage = process.memory_info().rss / 1024 / 1024
    logger.info(
        "Resource usage | RSS: %.2f MB | Cached messages: %s",
        memory_usage,
        len(bot.cached_messages),
    )
    check_memory_and_exit(limit_mb=APP_MEMORY_LIMIT_MB)
    if memory_usage > APP_MEMORY_LIMIT_MB * 0.9:
        logger.warning("Memory usage is approaching the configured limit (%.2f MB).", memory_usage)


@report_resource_usage.before_loop
async def before_report_resource_usage() -> None:
    await bot.wait_until_ready()


async def _perform_model_refresh(reason: str) -> None:
    models = await refresh_free_models()
    if models:
        top = models[0]
        logger.info(
            "Free model refresh (%s) candidate: %s (context %s tokens). Active model: %s",
            reason,
            top["id"],
            top["context_tokens"],
            get_current_model(),
        )
        preview = ", ".join(
            f"{entry['id']}({entry['context_tokens']})" for entry in models[:5]
        )
        logger.debug("Top free models (%s): %s", reason, preview)
    else:
        logger.warning(
            "Free model refresh (%s) found no available free models. Continuing with %s.",
            reason,
            get_current_model(),
        )


@tasks.loop(hours=FREE_MODEL_REFRESH_HOURS)
async def refresh_free_models_task() -> None:
    await _perform_model_refresh("scheduled")


@refresh_free_models_task.before_loop
async def before_refresh_free_models_task() -> None:
    await bot.wait_until_ready()


async def get_trump_posts(count: int = 1) -> List[str]:
    """Fetch recent Truth Social posts authored by Donald Trump."""
    count = max(1, min(count, 5))
    for attempt in range(1, POST_FETCH_RETRIES + 1):
        try:
            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(
                    headless=True,
                    args=["--disable-blink-features=AutomationControlled"],
                )
                context = await browser.new_context(
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                        "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                    )
                )
                page = await context.new_page()

                logger.info("Fetching %s Trump posts from Truth Social.", count)
                await page.goto(
                    "https://truthsocial.com/@realDonaldTrump",
                    wait_until="domcontentloaded",
                )
                await page.wait_for_timeout(5000)

                posts: List[str] = []
                max_scrolls = 25
                scroll_count = 0

                while len(posts) < count and scroll_count < max_scrolls:
                    post_elements = await page.locator("div.status__content-wrapper").all()
                    logger.debug("Located %s post elements on the page.", len(post_elements))
                    for post in post_elements:
                        if len(posts) >= count:
                            break
                        text_elements = await post.locator("p.text-base").all()
                        post_text = "\n".join([await t.inner_text() for t in text_elements])
                        clean_text = re.sub(r"http\S+", "", post_text).strip()
                        if clean_text and clean_text not in posts:
                            posts.append(clean_text)
                    if len(posts) < count:
                        await page.evaluate("window.scrollBy(0, 500)")
                        await asyncio.sleep(2)
                        scroll_count += 1

                await browser.close()

                if not posts:
                    logger.error("Unable to find any posts—site may be slow or layout changed.")
                    return ["❌ 未找到帖子！可能是网站加载过慢，请重试！"]

                logger.info("Successfully fetched %s posts from Truth Social.", len(posts))
                check_memory_and_exit(limit_mb=APP_MEMORY_LIMIT_MB)
                return posts
        except Exception:  # noqa: BLE001
            wait_time = POST_FETCH_RETRY_DELAY * attempt
            logger.exception("Attempt %s to fetch Trump posts failed.", attempt)
            if attempt == POST_FETCH_RETRIES:
                return ["❌ 未找到帖子！可能是网站加载过慢，请重试！"]
            await asyncio.sleep(wait_time)
    return ["❌ 未找到帖子！可能是网站加载过慢，请重试！"]


def select_valid_post(posts: List[str]) -> str:
    for post in posts:
        clean = post.strip().lower()
        if 20 < len(clean) < 300 and not re.match(r"^(thank|thanks|great|good|👍|🙏)", clean):
            return post
    return posts[0] if posts else "Trump posted something big and beautiful, folks!"


@bot.event
async def on_ready():
    logger.info("Bot %s is online and ready.", bot.user)


@bot.event
async def setup_hook():
    if not clear_message_cache.is_running():
        clear_message_cache.start()
    if not report_resource_usage.is_running():
        report_resource_usage.start()
    if not refresh_free_models_task.is_running():
        refresh_free_models_task.start()
    logger.debug("Background maintenance tasks have started.")


@bot.command()
async def trump(ctx, count: int = 1):
    count = max(1, min(count, 5))
    logger.info("Received /trump command requesting %s post(s).", count)
    posts = await get_trump_posts(count)
    for i, post in enumerate(posts, 1):
        await ctx.send(f"📢 **帖子 {i}**:\n{post}")


@bot.command()
async def trumpjoke(ctx, *, topic: str = ""):
    logger.info("Received /trumpjoke command with topic: %s", topic or "[latest post]")
    if topic:
        joke = await ask_ai(topic=topic)
    else:
        posts = await get_trump_posts(5)
        chosen = select_valid_post(posts)
        logger.debug("Using Trump post as prompt seed: %s", chosen)
        joke = await ask_ai(
            user=f'''Donald Trump just posted on Truth Social:

"{chosen}"

Write a funnier, bolder Trump-style reply to his own post. Be sarcastic, confident, and hilarious. One tweet only.'''
        )
    await ctx.send(f"{joke}")


@bot.event
async def on_message(message):
    if message.author == bot.user:
        return

    if bot.user.mentioned_in(message):
        content_lower = message.content.lower()
        logger.info("Mention received with content: %s", message.content)

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
            help_text = await ask_ai(user=help_prompt)
            await message.channel.send(f"📢 **TrumpBot Help**:\n{help_text}")
            return

        if "joke" in content_lower:
            posts = await get_trump_posts(5)
            chosen = select_valid_post(posts)
            logger.debug("@Bot joke selected post: %s", chosen)
            joke = await ask_ai(
                user=f'''Donald Trump just posted:

"{chosen}"

Now write a savage Trump-style tweet replying to himself. Go hard. One tweet only.'''
            )
            await message.channel.send(f"🧠**:{joke}")
            return

        match = re.search(r"\b([1-5])\b", message.content)
        count = int(match.group(1)) if match else 1
        count = max(1, min(count, 5))
        logger.info("Mention requested %s post(s).", count)
        posts = await get_trump_posts(count)
        for i, post in enumerate(posts, 1):
            await message.channel.send(f"📢 **帖子 {i}**:\n{post}")

    await bot.process_commands(message)


async def run_bot() -> None:
    if not TOKEN:
        logger.error("DISCORD_BOT_TOKEN is not configured. Exiting.")
        return

    await _perform_model_refresh("startup")

    retry_count = 0
    while True:
        try:
            await ensure_dependencies_ready()
            await bot.start(TOKEN, reconnect=True)
            break
        except discord.LoginFailure:
            logger.exception("Discord login failed due to invalid token. Exiting without retry.")
            return
        except (discord.HTTPException, discord.GatewayNotFound, OSError, httpx.HTTPError) as exc:
            retry_count += 1
            if STARTUP_RETRY_LIMIT and retry_count >= STARTUP_RETRY_LIMIT:
                logger.exception("Bot failed to start after %s attempts. Exiting.", retry_count)
                return
            wait_time = STARTUP_RETRY_DELAY * retry_count
            logger.warning(
                "Bot startup attempt %s failed: %s. Retrying in %s seconds.",
                retry_count,
                exc,
                wait_time,
            )
            await asyncio.sleep(wait_time)
        except Exception:  # noqa: BLE001
            logger.exception("Unexpected error during bot startup.")
            return

    if not bot.is_closed():
        await bot.close()


if __name__ == "__main__":
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logger.info("Shutdown requested by user (KeyboardInterrupt).")
