"""统一 DeepSeek 客户端。

职责（文档第 4 章）：
- chat 调用、JSON-mode 提示、schema 校验；
- 30s 超时 + 指数退避重试 2 次；
- 切换备用模型重试 1 次；
- 密钥只从环境变量读取，日志全量脱敏；
- 失败抛 DeepSeekError，由各服务触发 rule-based 兜底。
"""
from __future__ import annotations

import json
import logging
import time
from typing import Any, Optional

import httpx

from ..config import settings

logger = logging.getLogger("vibepcb.deepseek")


class DeepSeekError(RuntimeError):
    """DeepSeek 调用失败（触发调用方 rule-based 兜底）。"""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code  # DEEPSEEK_UNAVAILABLE / DEEPSEEK_KEY_MISSING


def mask_key(key: str) -> str:
    if not key:
        return "<empty>"
    return f"{key[:3]}***{key[-2:]}" if len(key) > 8 else "***"


class DeepSeekClient:
    """OpenAI 兼容 chat/completions 封装（DeepSeek 官方协议）。"""

    def __init__(self) -> None:
        self._client: Optional[httpx.Client] = None

    @property
    def client(self) -> httpx.Client:
        if self._client is None or self._client.is_closed:
            self._client = httpx.Client(
                base_url=settings.deepseek_base_url.rstrip("/"),
                timeout=settings.deepseek_timeout_s,
                headers={"Content-Type": "application/json"},
            )
        return self._client

    def close(self) -> None:
        if self._client and not self._client.is_closed:
            self._client.close()

    def chat_json(
        self,
        messages: list[dict[str, str]],
        *,
        model: Optional[str] = None,
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        """请求模型并解析 JSON 输出。三级降级链在此实现前两级（重试 + 备用模型），
        第三级（rule-based）由调用方实现。"""
        if not settings.deepseek_configured:
            raise DeepSeekError(
                "DEEPSEEK_KEY_MISSING", "DEEPSEEK_API_KEY 未配置（仅支持环境变量注入）"
            )

        primary = model or settings.deepseek_model
        # 第一级：主模型 + 2 次指数退避重试
        last_err: Optional[Exception] = None
        for attempt in range(1 + settings.deepseek_retries):
            try:
                return self._call_chat(primary, messages, max_tokens)
            except DeepSeekError as exc:  # JSON 解析类失败不重试换模型也无益，但重试无害
                last_err = exc
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_err = exc
            backoff = 2 ** attempt
            logger.warning(
                "deepseek call failed (attempt %s/%s): %s; retry in %ss",
                attempt + 1, 1 + settings.deepseek_retries, last_err, backoff,
            )
            time.sleep(backoff)

        # 第二级：备用模型重试 1 次
        if primary != settings.deepseek_fallback_model:
            logger.warning("primary model %s exhausted, trying fallback %s",
                           primary, settings.deepseek_fallback_model)
            try:
                return self._call_chat(settings.deepseek_fallback_model, messages, max_tokens)
            except Exception as exc:  # noqa: BLE001
                last_err = exc

        raise DeepSeekError(
            "DEEPSEEK_UNAVAILABLE",
            f"DeepSeek API 连续失败：{last_err}",
        )

    def _call_chat(
        self, model: str, messages: list[dict[str, str]], max_tokens: int
    ) -> dict[str, Any]:
        payload = {
            "model": model,
            "messages": messages,
            "response_format": {"type": "json_object"},
            "max_tokens": max_tokens,
            "temperature": 0.2,
        }
        headers = {}
        if settings.deepseek_api_key:
            # 密钥仅进入请求头；任何日志输出前都会经 mask_key。
            headers["Authorization"] = f"Bearer {settings.deepseek_api_key}"
        resp = self.client.post("/chat/completions", json=payload, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        content = data["choices"][0]["message"]["content"]
        return self._loads(content)

    @staticmethod
    def _loads(content: str) -> dict[str, Any]:
        text = content.strip()
        # 容错：剥掉 ```json 围栏
        if text.startswith("```"):
            text = text.strip("`")
            if text.lower().startswith("json"):
                text = text[4:]
        try:
            obj = json.loads(text)
        except json.JSONDecodeError as exc:
            raise DeepSeekError("DEEPSEEK_UNAVAILABLE", f"模型输出不是合法 JSON：{exc}") from exc
        if not isinstance(obj, dict):
            raise DeepSeekError("DEEPSEEK_UNAVAILABLE", "模型输出不是 JSON 对象")
        return obj


# 进程级单例
deepseek_client = DeepSeekClient()
