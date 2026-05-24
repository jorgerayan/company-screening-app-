"""
OpenAI async client — second-pass analysis validator layer.

Mirrors the interface of gemini_client.py so callers treat both identically.
Used exclusively by analysis_validator.py; not called directly by pipeline modules.

Degrades gracefully when OPENAI_API_KEY is absent: callers must check
settings.openai_api_key before calling this client.
"""
import asyncio
import json
import time
from typing import Any, Dict, List, Optional

from tenacity import (
    retry,
    retry_if_not_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Generous timeout for the validator: it receives a large payload and the
# model needs time to reason through the full analysis.
_VALIDATOR_TIMEOUT_SECONDS = 180


class OpenAIClient:
    """
    Async OpenAI client for structured JSON generation.

    Lazy-initializes the underlying AsyncOpenAI client so import errors are
    only raised when the client is actually used (not at startup when the key
    may legitimately be absent).
    """

    def __init__(self) -> None:
        self._client = None

    def _get_client(self):
        if self._client is None:
            try:
                from openai import AsyncOpenAI  # noqa: PLC0415
            except ImportError as e:
                raise RuntimeError(
                    "openai package is not installed. "
                    "Run: pip install 'openai>=1.30.0'"
                ) from e
            if not settings.openai_api_key:
                raise RuntimeError(
                    "OPENAI_API_KEY is not configured. "
                    "Set it in .env or the environment to enable the validator."
                )
            self._client = AsyncOpenAI(
                api_key=settings.openai_api_key,
                timeout=_VALIDATOR_TIMEOUT_SECONDS,
            )
        return self._client

    @retry(
        stop=stop_after_attempt(2),
        wait=wait_exponential(multiplier=1, min=4, max=20),
        retry=retry_if_not_exception_type((asyncio.TimeoutError, RuntimeError)),
    )
    async def generate_structured(
        self,
        system_prompt: str,
        user_prompt: str,
        expected_keys: Optional[List[str]] = None,
        temperature: float = 0.1,
        max_output_tokens: int = 16_384,
    ) -> Dict[str, Any]:
        """
        Call OpenAI and return parsed JSON.

        Returns {"data": dict, "duration_ms": int}.
        Raises ValueError on invalid JSON response.
        """
        client = self._get_client()
        start = time.monotonic()

        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=settings.openai_model,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                response_format={"type": "json_object"},
                temperature=temperature,
                max_tokens=max_output_tokens,
            ),
            timeout=_VALIDATOR_TIMEOUT_SECONDS,
        )

        duration_ms = int((time.monotonic() - start) * 1000)
        choice = response.choices[0]
        raw = choice.message.content or ""

        # Detect output truncation BEFORE attempting JSON parse.
        # finish_reason="length" means max_tokens was hit mid-response → JSON is
        # guaranteed to be incomplete regardless of response_format.
        finish_reason = choice.finish_reason
        if finish_reason == "length":
            raise ValueError(
                f"OpenAI output truncated (finish_reason=length, "
                f"max_tokens={max_output_tokens}). Analysis payload too large for "
                f"validator output window. Raw tail (100 chars): {raw[-100:]!r}"
            )

        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"OpenAI returned invalid JSON (finish_reason={finish_reason!r}): "
                f"{exc}. Raw (first 300 chars): {raw[:300]!r}"
            ) from exc

        if expected_keys:
            missing = [k for k in expected_keys if k not in data]
            if missing:
                logger.warning(
                    f"OpenAI response missing expected keys: {missing}. "
                    f"Available keys: {list(data.keys())}"
                )

        logger.info(
            f"OpenAI call completed in {duration_ms}ms "
            f"(model={settings.openai_model}, "
            f"output_keys={list(data.keys())})"
        )
        return {"data": data, "duration_ms": duration_ms}


openai_client = OpenAIClient()
