"""LLM 服务 — OpenAI 兼容 Chat Completions API 的轻量封装。

设计：单一方法、简单重试、无 provider 抽象层。
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import Optional

import aiosqlite
from openai import AsyncOpenAI

from .config import config


class LLMService:
    """极简的 OpenAI 兼容 LLM 客户端，支持可选的 SQLite 缓存。"""

    def __init__(self, db: Optional[aiosqlite.Connection] = None):
        self._client = AsyncOpenAI(
            base_url=config.llm_base_url,
            api_key=config.llm_api_key,
            timeout=config.llm_timeout_seconds,
        )
        self._model = config.llm_model
        self._db = db

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------

    async def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        *,
        temperature: float = 0.3,
        max_tokens: int = 2048,
        cache_key: Optional[str] = None,
    ) -> str:
        """发送 Chat Completion 请求，返回消息内容。

        如果提供了 cache_key 且缓存命中，则直接返回缓存结果，不调用 LLM。
        """
        # 1. 检查缓存
        if cache_key and self._db:
            cached = await self._load_cache(cache_key)
            if cached is not None:
                return cached

        # 2. 调用 LLM（带简单重试）
        content = await self._call_with_retry(
            system_prompt, user_prompt, temperature, max_tokens
        )

        # 3. 存入缓存
        if cache_key and self._db:
            await self._save_cache(cache_key, content)

        return content

    @staticmethod
    def make_cache_key(repo_url: str, readme_hash: str) -> str:
        """基于仓库标识 + 内容哈希生成确定性缓存键。"""
        raw = f"{repo_url}|{readme_hash}|{config.llm_model}"
        return hashlib.sha256(raw.encode()).hexdigest()[:32]

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------

    async def _call_with_retry(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        max_tokens: int,
        max_retries: int = 2,
    ) -> str:
        """在瞬时失败时最多重试 max_retries 次。"""
        last_error: Optional[Exception] = None

        for attempt in range(max_retries + 1):
            try:
                response = await self._client.chat.completions.create(
                    model=self._model,
                    messages=[
                        {"role": "system", "content": system_prompt},
                        {"role": "user", "content": user_prompt},
                    ],
                    temperature=temperature,
                    max_tokens=max_tokens,
                    response_format={"type": "json_object"},
                )
                return response.choices[0].message.content or "{}"

            except Exception as exc:
                last_error = exc
                if attempt < max_retries:
                    await asyncio.sleep(2 ** attempt)

        raise RuntimeError(
            f"LLM 调用失败（已重试 {max_retries + 1} 次）: {last_error}"
        )

    async def _load_cache(self, cache_key: str) -> Optional[str]:
        """从数据库加载 LLM 缓存响应。"""
        from .db import get_llm_cache

        assert self._db is not None
        return await get_llm_cache(self._db, cache_key)

    async def _save_cache(self, cache_key: str, response: str) -> None:
        """将 LLM 响应保存到缓存。"""
        from .db import set_llm_cache

        assert self._db is not None
        await set_llm_cache(self._db, cache_key, response)
