"""OpenAI 兼容 LLM 客户端（最小实现）。

配置来源：命令行参数 > 环境变量（含项目根 ``.env``）：
``OPENAI_MODEL`` / ``OPENAI_API_KEY`` / ``OPENAI_BASE_URL``。

``chat()`` 直接返回原始 message，由上层取 ``content`` / ``tool_calls``，不做多余封装。
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
_CODE_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_json(text: str) -> Any:
    """解析模型输出的 JSON；json_object 降级路径可能带代码块/废话，做容错提取。"""
    for candidate in _CODE_FENCE.findall(text or "") + [text or ""]:
        try:
            return json.loads(candidate.strip())
        except json.JSONDecodeError:
            continue
    for opener, closer in (("{", "}"), ("[", "]")):
        start, end = (text or "").find(opener), (text or "").rfind(closer)
        if start != -1 and end > start:
            try:
                return json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"无法解析 JSON: {(text or '')[:200]}")


@dataclass
class LLMConfig:
    model: str
    api_key: str
    base_url: str
    temperature: float = 0.0
    max_tokens: int = 16384  # 推理模型思考(reasoning)计入输出上限；部分服务端会 clamp 小值
    timeout: float = 120.0
    max_retries: int = 3

    @classmethod
    def from_env(cls, **overrides) -> LLMConfig:
        """读环境变量（含项目根 .env），命令行参数用 overrides 覆盖。"""
        try:
            from dotenv import load_dotenv
        except ImportError:
            pass
        else:
            load_dotenv(_PROJECT_ROOT / ".env", override=False)

        def pick(name: str, key: str) -> str:
            value = overrides.get(key)
            return str(value) if value is not None else os.getenv(name, "")

        model = pick("OPENAI_MODEL", "model")
        api_key = pick("OPENAI_API_KEY", "api_key")
        base_url = pick("OPENAI_BASE_URL", "base_url")
        if not (model and api_key and base_url):
            raise ValueError(
                "缺少 OPENAI_MODEL / OPENAI_API_KEY / OPENAI_BASE_URL"
                "（命令行 --model/--api-key/--base-url，或项目根 .env）"
            )

        return cls(
            model=model,
            api_key=api_key,
            base_url=base_url.rstrip("/"),
            temperature=overrides.get("temperature") or 0.0,
            max_tokens=overrides.get("max_tokens") or 16384,
            timeout=overrides.get("timeout") or 120.0,
            max_retries=overrides.get("max_retries") or 3,
        )


class LLM:
    """聊天客户端。重试交给 openai SDK（max_retries）。"""

    def __init__(self, config: LLMConfig):
        self._cfg = config
        self.model = config.model
        self._client = AsyncOpenAI(
            api_key=config.api_key,
            base_url=config.base_url,
            timeout=config.timeout,
            max_retries=config.max_retries,
        )

    async def chat(
        self,
        messages: list[dict[str, Any]],
        tools: list[dict[str, Any]] | None = None,
        tool_choice: str = "auto",
        json_mode: bool = False,
    ):
        """发起对话，返回 ChatCompletionMessage（content / tool_calls）。

        ``json_mode=True`` 设 ``response_format={"type": "json_object"}``，
        要求提示词中出现 "json" 字样；调用方用 ``Model.model_validate_json(content)`` 解析。
        """
        kwargs: dict[str, Any] = {
            "model": self._cfg.model,
            "messages": messages,
            "temperature": self._cfg.temperature,
            "max_tokens": self._cfg.max_tokens,
        }
        if tools:
            kwargs["tools"] = tools
            kwargs["tool_choice"] = tool_choice
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
            # 推理模型偶发空 content（服务端间歇性问题），退避重试
            completion = None
            for attempt in range(5):
                completion = await self._client.chat.completions.create(**kwargs)
                if (completion.choices[0].message.content or "").strip():
                    return completion.choices[0].message
                wait = 2**attempt
                usage = getattr(completion, "usage", None)
                logger.warning(
                    "json_object 空响应(finish=%s, out=%s, reasoning=%s)，%ds 后重试 %d/5",
                    completion.choices[0].finish_reason,
                    usage.completion_tokens if usage else "?",
                    getattr(getattr(usage, "completion_tokens_details", None), "reasoning_tokens", "?")
                    if usage else "?",
                    wait, attempt + 1,
                )
                await asyncio.sleep(wait)
            # 降级：部分长 prompt 下 json_object 稳定输出空，去掉约束再试一次
            logger.warning("json_object 持续空响应，降级为普通请求")
            kwargs.pop("response_format")
            completion = await self._client.chat.completions.create(**kwargs)
            return completion.choices[0].message
        return (await self._client.chat.completions.create(**kwargs)).choices[0].message

    async def aclose(self) -> None:
        await self._client.close()
