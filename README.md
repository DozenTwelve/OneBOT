# 🇺🇸 TrumpBot

**TrumpBot** is a Discord bot that scrapes the latest Truth Social posts from Donald Trump and uses an AI language model to generate sarcastic, bold, Trump-style responses.

## 🧠 Features

- `/trump [1~5]`  
  Scrape the most recent 1–5 posts from Trump’s official Truth Social page.

- `/trumpjoke [topic]`  
  Generate a bold, over-the-top Trump-style tweet based on a given topic. If no topic is provided, it will use one of Trump's own recent posts.

- `@TrumpBot joke`  
  Get a joke based on a recent Trump post.

- `@TrumpBot 3`  
  Fetch 3 latest Truth Social posts.

- `@TrumpBot help`  
  Show a help message written in character.

## 🚀 Getting Started

1. Copy `.env` from your secrets template and add the required keys:
   ```ini
   DISCORD_BOT_TOKEN=your_bot_token
   OPENROUTER_API_KEY=your_openrouter_key
   # Optional overrides
   LOG_LEVEL=INFO
   APP_MEMORY_LIMIT_MB=1900
   OPENROUTER_AUTO_SELECT_FREE=true
   OPENROUTER_FREE_MODEL_REFRESH_HOURS=168
   ```
2. Build and run the bot with Docker Compose (creates a Chromium-enabled container and enforces resource limits):
   ```bash
   docker compose up --build -d
   ```
3. Tail the logs to verify successful start-up and monitor the health loops:
   ```bash
   docker compose logs -f
   ```

## 🛠 Deployment Options

- **Docker Compose:** `docker-compose.yml` configures `restart: unless-stopped`, sets Google DNS (`8.8.8.8`), and enforces a 1 GiB memory ceiling (`mem_limit`). A lightweight container healthcheck (`python /app/healthcheck.py`) verifies that the bot process is present. Adjust the limits or retry timings through environment variables if needed.
- **Systemd wrapper:** the sample unit at `systemd/trumpbot.service` runs `docker compose up` in the foreground so systemd can restart it automatically. Update `WorkingDirectory` to your project path, copy it to `/etc/systemd/system/trumpbot.service`, then enable/start with:
  ```bash
  sudo systemctl daemon-reload
  sudo systemctl enable --now trumpbot.service
  ```

## ⚙️ Runtime Behaviour

- Startup waits for Truth Social readiness before connecting to Discord and automatically retries transient failures.
- Discord caching is trimmed (`max_messages=100`) and only the required intents (guilds, messages, message content) are enabled to reduce memory usage.
- Background tasks periodically clear the cached message deque and publish resource usage metrics so you can observe memory trends in the logs.
- Once a week (configurable), the bot queries OpenRouter for the currently-free models, sorts them by context window size, and switches to the best option automatically when `OPENROUTER_AUTO_SELECT_FREE` is enabled.
- To protect your OpenRouter balance, only models whose ID or name contains the word “free” are ever selected; if none are available the AI features pause until a free model returns.
- All prints were replaced with Python logging; configure verbosity via `LOG_LEVEL` (e.g., `DEBUG`, `INFO`, `WARNING`).

## 🧪 Operational Checks

- The bot exits if RSS usage exceeds `APP_MEMORY_LIMIT_MB` (default 1 900 MB). Pair this with the Docker memory ceiling for predictable resource bound.
- Health and scrape retries are configurable via:
  - `TRUMPBOT_FETCH_RETRIES`, `TRUMPBOT_FETCH_RETRY_DELAY`
  - `TRUMPBOT_STARTUP_RETRIES`, `TRUMPBOT_STARTUP_RETRY_DELAY`
  - `APP_MEMORY_LIMIT_MB` (also used inside the container monitoring loop)
