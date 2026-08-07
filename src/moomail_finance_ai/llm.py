from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Literal, Mapping, Protocol

from pydantic import Field

from moomail_finance_ai.config import load_env_file
from moomail_finance_ai.schemas import StrictModel


class GeminiConfig(StrictModel):
    provider: Literal["gemini"] = "gemini"
    api_key: str = Field(min_length=1)
    model: str = Field(min_length=1)
    base_url: str = "https://generativelanguage.googleapis.com/v1beta"


class OpenAIConfig(StrictModel):
    provider: Literal["openai"] = "openai"
    api_key: str = Field(min_length=1)
    model: str = Field(min_length=1)
    base_url: str = "https://api.openai.com/v1"


class TextLLMClient(Protocol):
    config: GeminiConfig | OpenAIConfig

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        max_output_tokens: int = 2048,
        temperature: float = 0.1,
        timeout: int = 60,
    ) -> str: ...


class TextGenerationResult(StrictModel):
    text: str
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    total_tokens: int | None = Field(default=None, ge=0)


class GeminiLLMError(RuntimeError):
    """Raised when Gemini cannot complete a text generation call."""


class OpenAILLMError(RuntimeError):
    """Raised when OpenAI cannot complete a text generation call."""


def build_llm_client_from_env(
    *,
    provider: str | None = None,
    env_file: str | Path | None = "config/local.env",
    env: Mapping[str, str] | None = None,
) -> TextLLMClient:
    merged = _merged_env(env_file, env=env)
    provider = (provider or merged.get("MOOMAIL_PORTFOLIO_AGENT_LLM_PROVIDER") or "gemini").lower()
    if provider == "gemini":
        return GeminiLLMClient(load_gemini_config(env=merged))
    if provider == "openai":
        return OpenAILLMClient(load_openai_config(env=merged))
    raise ValueError(f"Unsupported LLM provider: {provider}")


def load_gemini_config(
    *,
    env: Mapping[str, str] | None = None,
    env_file: str | Path | None = None,
) -> GeminiConfig:
    merged = _merged_env(env_file, env=env)

    api_key = (
        merged.get("MOOMAIL_GEMINI_API_KEY")
        or merged.get("GEMINI_API_KEY")
        or merged.get("GOOGLE_API_KEY")
        or ""
    )
    model = merged.get("MOOMAIL_GEMINI_MODEL") or ""
    base_url = merged.get("MOOMAIL_GEMINI_BASE_URL") or GeminiConfig.model_fields["base_url"].default
    return GeminiConfig(api_key=api_key, model=model, base_url=str(base_url).rstrip("/"))


def load_openai_config(
    *,
    env: Mapping[str, str] | None = None,
    env_file: str | Path | None = None,
) -> OpenAIConfig:
    merged = _merged_env(env_file, env=env)
    api_key = (
        merged.get("MOOMAIL_OPENAI_API_KEY")
        or merged.get("OPENAI_API_KEY")
        or merged.get("MOOMAIL_LLM_API_KEY")
        or ""
    )
    model = merged.get("MOOMAIL_OPENAI_MODEL") or merged.get("MOOMAIL_LLM_MODEL") or ""
    base_url = (
        merged.get("MOOMAIL_OPENAI_BASE_URL")
        or merged.get("MOOMAIL_LLM_BASE_URL")
        or OpenAIConfig.model_fields["base_url"].default
    )
    return OpenAIConfig(api_key=api_key, model=model, base_url=str(base_url).rstrip("/"))


class GeminiLLMClient:
    def __init__(self, config: GeminiConfig):
        self.config = config

    @classmethod
    def from_env(cls, *, env_file: str | Path | None = "config/local.env") -> GeminiLLMClient:
        return cls(load_gemini_config(env_file=env_file))

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        max_output_tokens: int = 2048,
        temperature: float = 0.1,
        timeout: int = 60,
    ) -> str:
        return self.generate_text_result(
            prompt,
            system_instruction=system_instruction,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            timeout=timeout,
        ).text

    def generate_text_result(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        max_output_tokens: int = 2048,
        temperature: float = 0.1,
        timeout: int = 60,
    ) -> TextGenerationResult:
        model_path = self.config.model
        if not model_path.startswith("models/"):
            model_path = f"models/{model_path}"
        encoded_model_path = urllib.parse.quote(model_path, safe="/")
        payload: dict[str, Any] = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "maxOutputTokens": max_output_tokens,
                "temperature": temperature,
            },
        }
        if system_instruction:
            payload["systemInstruction"] = {"parts": [{"text": system_instruction}]}

        response = self._request_json(
            f"{self.config.base_url}/{encoded_model_path}:generateContent",
            payload=payload,
            timeout=timeout,
        )
        text = _gemini_response_text(response)
        if not text.strip():
            raise GeminiLLMError("Gemini call succeeded, but no text output could be extracted.")
        usage = _gemini_response_usage(response)
        return TextGenerationResult(text=text, **usage)

    def _request_json(self, url: str, *, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "x-goog-api-key": self.config.api_key,
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise GeminiLLMError(f"Gemini HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise GeminiLLMError(f"Gemini request failed: {exc}") from exc
        return json.loads(raw.decode("utf-8")) if raw else {}


class OpenAILLMClient:
    def __init__(self, config: OpenAIConfig):
        self.config = config

    @classmethod
    def from_env(cls, *, env_file: str | Path | None = "config/local.env") -> OpenAILLMClient:
        return cls(load_openai_config(env_file=env_file))

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        max_output_tokens: int = 2048,
        temperature: float = 0.1,
        timeout: int = 60,
    ) -> str:
        return self.generate_text_result(
            prompt,
            system_instruction=system_instruction,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            timeout=timeout,
        ).text

    def generate_text_result(
        self,
        prompt: str,
        *,
        system_instruction: str | None = None,
        max_output_tokens: int = 2048,
        temperature: float = 0.1,
        timeout: int = 60,
    ) -> TextGenerationResult:
        input_payload: list[dict[str, str]] | str
        if system_instruction:
            input_payload = [
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt},
            ]
        else:
            input_payload = prompt
        payload: dict[str, Any] = {
            "model": self.config.model,
            "input": input_payload,
            "max_output_tokens": max_output_tokens,
            "temperature": temperature,
        }
        response = self._request_json(
            f"{self.config.base_url}/responses",
            payload=payload,
            timeout=timeout,
        )
        text = _openai_response_text(response)
        if not text.strip():
            raise OpenAILLMError("OpenAI call succeeded, but no text output could be extracted.")
        usage = _openai_response_usage(response)
        return TextGenerationResult(text=text, **usage)

    def _request_json(self, url: str, *, payload: dict[str, Any], timeout: int) -> dict[str, Any]:
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise OpenAILLMError(f"OpenAI HTTP {exc.code}: {body}") from exc
        except urllib.error.URLError as exc:
            raise OpenAILLMError(f"OpenAI request failed: {exc}") from exc
        return json.loads(raw.decode("utf-8")) if raw else {}


def _gemini_response_text(response: dict[str, Any]) -> str:
    parts: list[str] = []
    for candidate in response.get("candidates", []):
        content = candidate.get("content", {})
        for part in content.get("parts", []):
            text = part.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _openai_response_text(response: dict[str, Any]) -> str:
    if isinstance(response.get("output_text"), str):
        return response["output_text"]
    parts: list[str] = []
    for item in response.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "\n".join(parts)


def _gemini_response_usage(response: dict[str, Any]) -> dict[str, int | None]:
    usage = response.get("usageMetadata")
    if not isinstance(usage, dict):
        return {"input_tokens": None, "output_tokens": None, "total_tokens": None}
    return {
        "input_tokens": _optional_nonnegative_int(usage.get("promptTokenCount")),
        "output_tokens": _optional_nonnegative_int(usage.get("candidatesTokenCount")),
        "total_tokens": _optional_nonnegative_int(usage.get("totalTokenCount")),
    }


def _openai_response_usage(response: dict[str, Any]) -> dict[str, int | None]:
    usage = response.get("usage")
    if not isinstance(usage, dict):
        return {"input_tokens": None, "output_tokens": None, "total_tokens": None}
    return {
        "input_tokens": _optional_nonnegative_int(usage.get("input_tokens")),
        "output_tokens": _optional_nonnegative_int(usage.get("output_tokens")),
        "total_tokens": _optional_nonnegative_int(usage.get("total_tokens")),
    }


def _optional_nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def _merged_env(
    env_file: str | Path | None = None,
    *,
    env: Mapping[str, str] | None = None,
) -> dict[str, str]:
    merged = dict(os.environ if env is None else env)
    if env_file is not None and Path(env_file).expanduser().exists():
        merged.update(load_env_file(env_file))
    return merged
