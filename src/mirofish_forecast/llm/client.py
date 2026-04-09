"""OpenAI client wrapper with retry, rate limiting, and structured output support."""

import logging

from openai import APIConnectionError, APITimeoutError, OpenAI, RateLimitError
from pydantic import BaseModel
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from mirofish_forecast.config.settings import Settings

logger = logging.getLogger(__name__)

# Retry on transient errors only
_RETRYABLE_ERRORS = (APITimeoutError, RateLimitError, APIConnectionError)


class LLMClient:
    """Synchronous OpenAI client with retry and structured output."""

    def __init__(self, settings: Settings) -> None:
        self._client = OpenAI(api_key=settings.openai_api_key)
        self._settings = settings

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_ERRORS),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def parse_structured(
        self,
        system_prompt: str,
        user_message: str,
        response_format: type[BaseModel],
        model: str | None = None,
        temperature: float = 0.0,
        max_tokens: int = 500,
        timeout: int = 15,
    ) -> BaseModel:
        """Call GPT with structured output (response_format) and return a Pydantic model.

        Uses OpenAI's `response_format` parameter with `type: "json_schema"`
        for guaranteed schema compliance.
        """
        model = model or self._settings.openai_model_parse

        logger.info(f"LLM parse_structured call: model={model}, format={response_format.__name__}")

        completion = self._client.beta.chat.completions.parse(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            response_format=response_format,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

        parsed = completion.choices[0].message.parsed
        if parsed is None:
            # Refusal or failed parse
            refusal = completion.choices[0].message.refusal
            raise ValueError(f"LLM refused to parse: {refusal}")

        logger.info("LLM parse_structured succeeded")
        return parsed

    @retry(
        retry=retry_if_exception_type(_RETRYABLE_ERRORS),
        wait=wait_exponential(multiplier=1, min=1, max=30),
        stop=stop_after_attempt(3),
        reraise=True,
    )
    def chat(
        self,
        system_prompt: str,
        user_message: str,
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1000,
        timeout: int = 30,
    ) -> str:
        """Simple chat completion. Returns the text response."""
        model = model or self._settings.openai_model_parse

        completion = self._client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_message},
            ],
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
        )

        return completion.choices[0].message.content or ""
