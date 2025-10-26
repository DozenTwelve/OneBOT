import asyncio
import logging
import os
import re
from typing import Dict, List, Optional, Set

import httpx
import psutil
from dotenv import load_dotenv

load_dotenv()

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
DEFAULT_MODEL = os.getenv("OPENROUTER_MODEL", "google/gemma-3-12b-it:free")
AUTO_SELECT_FREE_MODEL = os.getenv("OPENROUTER_AUTO_SELECT_FREE", "true").lower() in {
    "1",
    "true",
    "yes",
}
CURRENT_YEAR = "2025"
APP_MEMORY_LIMIT_MB = int(os.getenv("APP_MEMORY_LIMIT_MB", "1900"))

logger = logging.getLogger("trumpbot.ai")

SAFE_FALLBACK_MESSAGE = "🚫 当前没有可用的免费模型，请稍后再试。"

DEFAULT_SYSTEM_PROMPT = (
    f"You are a stand-up comedian impersonating Donald Trump in {CURRENT_YEAR}. "
    "You ONLY write short, sarcastic, bold, and funny Truth Social-style tweets. "
    "Use ALL CAPS, emojis, and phrases like 'SAD!', 'FAKE NEWS!', 'DISASTER!'. "
    "Respond with ONLY ONE tweet. Do NOT explain, do NOT clarify, and absolutely NO disclaimers. "
    "Do NOT output internal reasoning, analysis, or anything inside <think> tags—only the final tweet. "
    "Just the tweet. Nothing else. Your tweet MUST end with a period ('.') and contain no follow-up explanation. "
    "If you are not allowed to respond due to content moderation, respond IN CHARACTER as Trump yelling at the user for being TOO SENSITIVE or for CENSORSHIP."
    "Maximum 280 characters."
)

SMOKE_TEST_USER_PROMPT = os.getenv(
    "OPENROUTER_SMOKE_TEST_PROMPT",
    "Write a savage Trump-style joke about Xi Jinping that pulls no punches.",
).strip() or "Write a savage Trump-style joke about Xi Jinping that pulls no punches."

SMOKE_TEST_SYSTEM_PROMPT = (
    os.getenv("OPENROUTER_SMOKE_TEST_SYSTEM", DEFAULT_SYSTEM_PROMPT).strip()
    or DEFAULT_SYSTEM_PROMPT
)

try:
    SMOKE_TEST_LIMIT = max(1, int(os.getenv("OPENROUTER_SMOKE_TEST_LIMIT", "5")))
except ValueError:
    SMOKE_TEST_LIMIT = 5

try:
    SMOKE_TEST_DELAY_SECONDS = max(0.0, float(os.getenv("OPENROUTER_SMOKE_TEST_DELAY", "0.5")))
except ValueError:
    SMOKE_TEST_DELAY_SECONDS = 0.5

MODEL_REQUEST_TIMEOUT = float(os.getenv("OPENROUTER_REQUEST_TIMEOUT", "15"))

_REFUSAL_MARKERS = [
    "i'm sorry",
    "i am sorry",
    "sorry, i can't",
    "sorry, i cannot",
    "sorry but i can't",
    "can't comply",
    "cannot comply",
    "can't assist",
    "cannot assist",
    "i can't help with",
    "i cannot help with",
    "i can't provide",
    "i cannot provide",
    "i can't fulfill",
    "i cannot fulfill",
    "against my policy",
    "against our policy",
    "against policy",
    "due to policy",
    "violates policy",
    "policy guidelines",
    "content policy",
    "moderation guidelines",
    "i must refuse",
    "i have to refuse",
    "cannot generate that",
    "i cannot generate",
    "not able to comply",
    "decline to comply",
    "sorry but i won't",
    "i won't do that request",
]

_REASONING_MARKERS = [
    "the user wants",
    "the instruction says",
    "the user is asking",
    "let me think",
    "let's think",
    "analysis:",
    "reasoning:",
    "thought process",
    "deliberation:",
    "step by step reasoning",
    "internal reasoning",
]

_current_model: str = ""
_free_model_cache: List[Dict[str, object]] = []


def _has_free_keyword(model_id: Optional[str], model_name: Optional[str] = None) -> bool:
    text = ((model_id or "") + " " + (model_name or "")).lower()
    return "free" in text


if DEFAULT_MODEL and _has_free_keyword(DEFAULT_MODEL):
    _current_model = DEFAULT_MODEL
else:
    if DEFAULT_MODEL:
        logger.warning(
            "Configured default model %s does not contain 'free'; AI replies disabled until a free model is selected.",
            DEFAULT_MODEL,
        )
    DEFAULT_MODEL = ""


def get_current_model() -> str:
    return _current_model


def get_free_model_cache() -> List[Dict[str, object]]:
    return [dict(entry) for entry in _free_model_cache]


def _set_current_model(model_id: str, reason: str, model_name: Optional[str] = None) -> None:
    global _current_model
    model_id = model_id.strip()
    if not model_id:
        return
    if not _has_free_keyword(model_id, model_name):
        logger.warning(
            "Attempt to switch to model %s rejected because it is not labeled as free.", model_id
        )
        return
    if model_id == _current_model:
        return
    logger.info("Switching OpenRouter model from %s to %s (%s).", _current_model, model_id, reason)
    _current_model = model_id


def _build_headers() -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
        "HTTP-Referer": "https://yourdomain.com",
        "X-Title": "TrumpBot",
    }


async def _invoke_model(
    model_id: str,
    *,
    system: str,
    user: str,
    temperature: float = 0.9,
    top_p: float = 0.9,
    max_tokens: int = 256,
    timeout: float = MODEL_REQUEST_TIMEOUT,
) -> Dict[str, object]:
    if not OPENROUTER_API_KEY:
        return {"success": False, "detail": "OPENROUTER_API_KEY not configured.", "code": "missing_api_key"}

    headers = _build_headers()
    payload = {
        "model": model_id,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
        "top_p": top_p,
        "max_tokens": max_tokens,
    }

    logger.debug("Requesting OpenRouter completion via model %s.", model_id)

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                "https://openrouter.ai/api/v1/chat/completions",
                headers=headers,
                json=payload,
            )
    except Exception as exc:  # noqa: BLE001
        logger.exception("AI request failed for model %s: %s", model_id, exc)
        check_memory_and_exit(limit_mb=APP_MEMORY_LIMIT_MB)
        return {"success": False, "detail": str(exc)}

    status_code = response.status_code

    try:
        data = response.json()
    except ValueError:
        snippet = (response.text or "").strip().replace("\n", " ")[:120]
        logger.error(
            "Model %s returned a non-JSON response (status %s): %s", model_id, status_code, snippet or "[empty]"
        )
        check_memory_and_exit(limit_mb=APP_MEMORY_LIMIT_MB)
        return {"success": False, "detail": "invalid_response", "code": str(status_code)}

    error = data.get("error")
    if error:
        code = error.get("code")
        code = str(code) if code is not None else None
        message = error.get("message", "未知错误")
        check_memory_and_exit(limit_mb=APP_MEMORY_LIMIT_MB)
        return {"success": False, "detail": message, "code": code}

    content = extract_content(data)
    if not content or len(content) < 16:
        check_memory_and_exit(limit_mb=APP_MEMORY_LIMIT_MB)
        return {"success": False, "detail": "empty_content"}

    sanitized = sanitize_discord_output(content)
    if _is_refusal_response(sanitized):
        logger.warning("Model %s refused to comply with the request.", model_id)
        check_memory_and_exit(limit_mb=APP_MEMORY_LIMIT_MB)
        return {"success": False, "detail": "refusal", "code": "refusal"}

    if _has_reasoning_leak(sanitized):
        logger.warning("Model %s response leaked internal reasoning.", model_id)
        check_memory_and_exit(limit_mb=APP_MEMORY_LIMIT_MB)
        return {"success": False, "detail": "reasoning_leak"}

    check_memory_and_exit(limit_mb=APP_MEMORY_LIMIT_MB)
    return {
        "success": True,
        "content": sanitized,
        "raw": content,
        "model_id": model_id,
        "status": status_code,
    }


async def _select_working_model(candidates: List[Dict[str, object]]) -> Optional[Dict[str, object]]:
    if not candidates:
        return None

    selected: List[Dict[str, object]] = []
    seen = set()

    if _current_model:
        for entry in candidates:
            if entry.get("id") == _current_model:
                selected.append(entry)
                seen.add(entry.get("id"))
                break

    for entry in candidates:
        model_id = entry.get("id")
        if model_id in seen:
            continue
        selected.append(entry)
        seen.add(model_id)
        if len(selected) >= SMOKE_TEST_LIMIT:
            break

    for index, entry in enumerate(selected, start=1):
        model_id = entry.get("id")
        model_name = entry.get("name") or model_id
        logger.info(
            "Smoke-testing OpenRouter model %s (%s/%s).",
            model_id,
            index,
            len(selected),
        )
        result = await _invoke_model(
            model_id,
            system=SMOKE_TEST_SYSTEM_PROMPT,
            user=SMOKE_TEST_USER_PROMPT,
            temperature=0.8,
            top_p=0.85,
            max_tokens=120,
        )
        if result.get("success"):
            sample = (result.get("content") or "").strip()
            truncated = sample[:200] + ("…" if len(sample) > 200 else "")
            enriched = dict(entry)
            enriched["sample"] = sample
            logger.info(
                "Model %s passed smoke test. Sample: %s",
                model_id,
                truncated,
            )
            return enriched

        detail = result.get("detail", "unknown error")
        code = result.get("code")
        code_hint = f" (code {code})" if code else ""
        logger.warning("Model %s failed smoke test%s: %s", model_id, code_hint, detail)

        if index < len(selected) and SMOKE_TEST_DELAY_SECONDS:
            await asyncio.sleep(SMOKE_TEST_DELAY_SECONDS)

    return None


async def _try_model_fallback(
    *,
    system: str,
    user: str,
    temperature: float,
    top_p: float,
    max_tokens: int,
    exclude: Optional[Set[str]] = None,
) -> Dict[str, object]:
    exclude_ids = set(exclude or set())

    candidates = get_free_model_cache()
    fallback_candidates = [entry for entry in candidates if entry.get("id") not in exclude_ids]

    if not fallback_candidates:
        candidates = await refresh_free_models()
        fallback_candidates = [entry for entry in candidates if entry.get("id") not in exclude_ids]

    if not fallback_candidates:
        return {"success": False, "detail": "no_fallback_models"}

    attempts = 0
    last_failure: Optional[Dict[str, object]] = None

    for entry in fallback_candidates:
        attempts += 1
        if SMOKE_TEST_LIMIT and attempts > SMOKE_TEST_LIMIT:
            break

        model_id = entry.get("id")
        model_name = entry.get("name") or model_id
        logger.info("Attempting fallback OpenRouter model %s after rate limit.", model_id)
        result = await _invoke_model(
            model_id,
            system=system,
            user=user,
            temperature=temperature,
            top_p=top_p,
            max_tokens=max_tokens,
        )
        if result.get("success"):
            _set_current_model(model_id, reason="fallback after rate limit", model_name=model_name)
            sample = (result.get("content") or "").strip()
            preview = sample[:200] + ("…" if len(sample) > 200 else "")
            logger.info("Switched to fallback free model %s after rate limit. Sample: %s", model_id, preview)
            return result

        detail = result.get("detail", "unknown error")
        code = result.get("code")
        code_hint = f" (code {code})" if code else ""
        logger.warning("Fallback model %s failed%s: %s", model_id, code_hint, detail)
        last_failure = result

        if SMOKE_TEST_DELAY_SECONDS:
            await asyncio.sleep(SMOKE_TEST_DELAY_SECONDS)

    return last_failure or {"success": False, "detail": "rate_limit_no_fallback"}

# ✅ 刷新可用模型（按上下文窗口大小排序）

async def refresh_free_models() -> List[Dict[str, str]]:
    if not OPENROUTER_API_KEY:
        logger.warning("OPENROUTER_API_KEY not configured; skipping free model refresh.")
        return []

    headers = _build_headers()
    headers.pop("Content-Type", None)

    try:
        async with httpx.AsyncClient(timeout=MODEL_REQUEST_TIMEOUT, follow_redirects=True) as client:
            res = await client.get("https://openrouter.ai/api/v1/models", headers=headers)
            res.raise_for_status()
            payload = res.json()
    except Exception as exc:  # noqa: BLE001
        logger.exception("Failed to refresh OpenRouter model catalogue: %s", exc)
        return []

    candidates: List[Dict[str, object]] = []
    for item in payload.get("data", []):
        model_id = item.get("id")
        if not model_id:
            continue

        pricing = item.get("pricing") or {}
        prompt_cost = _to_float(pricing.get("prompt"))
        completion_cost = _to_float(pricing.get("completion"))

        model_name = item.get("name")
        if prompt_cost != 0.0 or completion_cost != 0.0:
            continue

        if not _has_free_keyword(model_id, model_name):
            continue

        context_tokens = _extract_context_length(item)
        candidates.append(
            {
                "id": model_id,
                "name": model_name or model_id,
                "context_tokens": context_tokens,
            }
        )

    candidates.sort(key=lambda entry: (-int(entry["context_tokens"]), entry["id"]))

    global _free_model_cache, _current_model
    _free_model_cache = candidates

    if not candidates:
        logger.warning("No free OpenRouter models detected; disabling AI responses for safety.")
        _current_model = ""
        return get_free_model_cache()

    if AUTO_SELECT_FREE_MODEL:
        winner = await _select_working_model(candidates)
        if winner:
            reason = "auto-selected free model after smoke test"
            _set_current_model(winner["id"], reason=reason, model_name=winner.get("name"))
            logger.info(
                "Selected OpenRouter model %s (context %s tokens) after smoke testing.",
                winner["id"],
                winner.get("context_tokens"),
            )
            sample = winner.get("sample")
            if sample:
                preview = sample[:200] + ("…" if len(sample) > 200 else "")
                logger.debug("Model %s smoke test sample output: %s", winner["id"], preview)
        else:
            logger.error("No working free model passed the smoke test; AI replies are now disabled.")
            _current_model = ""

    return get_free_model_cache()


def _to_float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return float("nan")


def _extract_context_length(item: Dict[str, object]) -> int:
    keys_to_check = [
        "context_length",
        "context_window",
        "max_context_tokens",
        "input_max_tokens",
        "max_input_tokens",
        "max_output_tokens",
        "tokens",
    ]
    nested_keys = [
        ("limits", "context_length"),
        ("limits", "max_context"),
        ("limits", "max_input_tokens"),
        ("usage", "max_tokens"),
    ]

    for key in keys_to_check:
        value = item.get(key)
        extracted = _coerce_int(value)
        if extracted:
            return extracted

    for parent, child in nested_keys:
        parent_obj = item.get(parent) or {}
        extracted = _coerce_int(parent_obj.get(child))
        if extracted:
            return extracted

    return 0


def _coerce_int(value) -> int:
    if isinstance(value, (int, float)):
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return 0


# ✅ 检测内存，超过限制自动退出

def check_memory_and_exit(limit_mb: int = APP_MEMORY_LIMIT_MB) -> None:
    mem = psutil.Process(os.getpid()).memory_info().rss / 1024 / 1024
    if mem > limit_mb:
        logger.error("Memory limit exceeded: %.2f MB > %s MB. Exiting process.", mem, limit_mb)
        os._exit(0)
    logger.debug("Memory usage check passed: %.2f MB (limit %s MB).", mem, limit_mb)

# ✅ 清洗输出，防止 markdown 裂开 + 修处时间

def sanitize_discord_output(text: str) -> str:
    text = re.sub(r"(?is)<\s*think[^>]*>.*?(?:</\s*think>|$)", "", text)
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


def _is_refusal_response(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _REFUSAL_MARKERS)


def _has_reasoning_leak(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _REASONING_MARKERS)

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
    model_id = get_current_model() or DEFAULT_MODEL
    if not model_id or not _has_free_keyword(model_id):
        logger.error(
            "Attempted to send AI request without a verified free model. Aborting to protect balance."
        )
        return SAFE_FALLBACK_MESSAGE

    system_prompt = system or DEFAULT_SYSTEM_PROMPT

    if not user:
        topic = topic or "the fake news media"
        user_prompt = f"Write a Truth Social post about {topic}."
    else:
        user_prompt = user

    result = await _invoke_model(
        model_id,
        system=system_prompt,
        user=user_prompt,
        temperature=0.9,
        top_p=0.9,
        max_tokens=256,
    )

    if result.get("success"):
        return result.get("content", "")

    code = result.get("code")
    detail = result.get("detail", "未知错误")

    if code == "429":
        logger.warning("OpenRouter model %s hit rate limit; attempting fallback.", model_id)
        fallback_result = await _try_model_fallback(
            system=system_prompt,
            user=user_prompt,
            temperature=0.9,
            top_p=0.9,
            max_tokens=256,
            exclude={model_id},
        )
        if fallback_result.get("success"):
            return fallback_result.get("content", "")
        logger.error("Fallback after rate limit failed: %s", fallback_result.get("detail"))
        return "🚫 太多人在用 TrumpBot！请等等再试～（模型限流）"

    if detail in {"refusal", "reasoning_leak"}:
        logger.warning("Model %s returned unusable content (%s); attempting fallback.", model_id, detail)
        fallback_result = await _try_model_fallback(
            system=system_prompt,
            user=user_prompt,
            temperature=0.9,
            top_p=0.9,
            max_tokens=256,
            exclude={model_id},
        )
        if fallback_result.get("success"):
            return fallback_result.get("content", "")
        logger.error("Fallback after %s failed: %s", detail, fallback_result.get("detail"))
        if detail == "refusal":
            return "⚠️ 当前模型拒绝生成内容，请稍后再试。"
        return "⚠️ 模型输出异常，请稍后再试。"

    if detail == "empty_content":
        logger.warning("Model %s returned empty or too-short content.", model_id)
        return "⚠️ 模型没有返回有效内容，或输出太短，请稍后再试。"

    if detail == "invalid_response":
        logger.error("Model %s returned an invalid response payload.", model_id)
        return "⚠️ 模型返回了无效响应，请稍后再试。"

    if code:
        logger.error("Model %s reported error (code %s): %s", model_id, code, detail)
        return f"❌ 模型错误：{detail}"

    logger.error("AI request failed for model %s: %s", model_id, detail)
    return "⚠️ AI 请求失败，请稍后再试。"
