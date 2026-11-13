"""Çoklu-model sohbet katmanı — tek arayüz: chat_complete().

Sağlayıcılar: glm (gömülü) • evren (OpenAI-uyumlu) • pollinations • ollama
• herhangi bir OpenAI-uyumlu endpoint • anthropic • gemini
Seçilen model başarısızsa FALLBACK_CHAIN sırayla denenir.
"""
import asyncio
import json
import os
from pathlib import Path

import httpx

from config import (BASE_DIR, FALLBACK_CHAIN, MODEL_CATALOG, SYSTEM_PROMPT,
                    default_model, model_available)

BRIDGE = BASE_DIR / "llm_bridge.mjs"


class ChatError(Exception):
    pass


# ---------------------------------------------------------------- glm
async def _glm(messages: list[dict]) -> str:
    proc = await asyncio.create_subprocess_exec(
        "node", str(BRIDGE),
        stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE, cwd=str(BASE_DIR),
    )
    try:
        out, err = await asyncio.wait_for(
            proc.communicate(json.dumps({"messages": messages}).encode()),
            timeout=120,
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise ChatError("GLM köprüsü zaman aşımı (120s)")
    try:
        data = json.loads(out.decode())
    except Exception:
        raise ChatError(f"GLM köprüsü yanıt vermedi: {err.decode()[:200]}")
    if "error" in data:
        raise ChatError(f"GLM: {data['error'][:200]}")
    return data["content"]


# ---------------------------------------------------------------- pollinations
async def _pollinations(messages: list[dict]) -> str:
    async with httpx.AsyncClient(timeout=90) as client:
        r = await client.post(
            "https://text.pollinations.ai/",
            json={"messages": messages, "model": "openai"},
        )
        r.raise_for_status()
        try:
            d = r.json()
            if isinstance(d, dict):
                if "choices" in d:
                    return d["choices"][0]["message"]["content"]
                return d.get("content") or json.dumps(d, ensure_ascii=False)[:500]
        except Exception:
            pass
        return r.text


# ---------------------------------------------------------------- ollama
async def _ollama(model: str, messages: list[dict]) -> str:
    base = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    async with httpx.AsyncClient(timeout=180) as client:
        r = await client.post(
            f"{base}/api/chat",
            json={"model": model, "messages": messages, "stream": False},
        )
        r.raise_for_status()
        return r.json()["message"]["content"]


# ---------------------------------------------------------------- openai-uyumlu
async def _openai_uyumlu(base: str, model: str, key: str,
                         messages: list[dict]) -> str:
    headers = {"Content-Type": "application/json"}
    if key:
        headers["Authorization"] = f"Bearer {key}"
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"{base.rstrip('/')}/chat/completions",
            headers=headers,
            json={"model": model, "messages": messages},
        )
        if r.status_code >= 400:
            raise ChatError(f"API HTTP {r.status_code}: {r.text[:200]}")
        return r.json()["choices"][0]["message"]["content"]


# ---------------------------------------------------------------- anthropic
async def _anthropic(model: str, key: str, messages: list[dict]) -> str:
    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    rest = [m for m in messages if m["role"] != "system"]
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": key,
                "anthropic-version": "2023-06-01",
                "Content-Type": "application/json",
            },
            json={"model": model, "max_tokens": 1024,
                  "system": system, "messages": rest},
        )
        if r.status_code >= 400:
            raise ChatError(f"Claude HTTP {r.status_code}: {r.text[:200]}")
        return r.json()["content"][0]["text"]


# ---------------------------------------------------------------- gemini
async def _gemini(model: str, key: str, messages: list[dict]) -> str:
    system = "\n".join(m["content"] for m in messages if m["role"] == "system")
    contents = [
        {"role": "user" if m["role"] == "user" else "model",
         "parts": [{"text": m["content"]}]}
        for m in messages if m["role"] != "system"
    ]
    body: dict = {"contents": contents}
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    async with httpx.AsyncClient(timeout=120) as client:
        r = await client.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
            params={"key": key}, json=body,
        )
        if r.status_code >= 400:
            raise ChatError(f"Gemini HTTP {r.status_code}: {r.text[:200]}")
        return r.json()["candidates"][0]["content"]["parts"][0]["text"]


# ---------------------------------------------------------------- yönlendirici
async def _call_model(mid: str, messages: list[dict]) -> tuple[str, str]:
    m = MODEL_CATALOG[mid]
    p = m["saglayici"]
    if p == "glm":
        return await _glm(messages), mid
    if p == "pollinations":
        return await _pollinations(messages), mid
    if p == "ollama":
        return await _ollama(m.get("model", "llama3.2"), messages), mid
    if p == "openai_uyumlu":
        if not m.get("base") or not m.get("model"):
            raise ChatError(f"{mid}: base/model ayarlı değil (.env'i doldur)")
        return await _openai_uyumlu(m["base"], m["model"], m.get("anahtar", ""), messages), mid
    if p == "anthropic":
        return await _anthropic(m["model"], m.get("anahtar", ""), messages), mid
    if p == "gemini":
        return await _gemini(m["model"], m.get("anahtar", ""), messages), mid
    raise ChatError(f"bilinmeyen sağlayıcı: {p}")


async def chat_complete(model_id: str, messages: list[dict]) -> tuple[str, str]:
    """(yanıt_metni, kullanılan_model_id) — fallback zinciriyle."""
    chain = [model_id] + [m for m in FALLBACK_CHAIN if m != model_id]
    errors: list[str] = []
    for mid in chain:
        if not model_available(mid):
            continue
        try:
            return await _call_model(mid, messages)
        except ChatError as e:
            errors.append(f"• {mid}: {e}")
        except Exception as e:
            errors.append(f"• {mid}: {type(e).__name__}: {str(e)[:150]}")
    raise ChatError("Tüm modeller başarısız oldu:\n" + "\n".join(errors[-3:]))


# ---------------------------------------------------------------- tam akış
async def ask_ai(chat_id: int, user_text: str) -> tuple[str, str]:
    """Sohbet hafızası + sistem promptu + kayıt. (yanıt, model) döner."""
    import database as db  # döngüsel importu burada kırmak için

    model = db.get_model(chat_id, default_model())
    history = db.get_chat_history(chat_id, 10)
    db.add_chat_msg(chat_id, "user", user_text)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    messages += history
    messages.append({"role": "user", "content": user_text})
    content, used = await chat_complete(model, messages)
    db.add_chat_msg(chat_id, "assistant", content, used)
    return content, used
