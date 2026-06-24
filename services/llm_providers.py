"""
LLM Abstraction Layer — Provider-agnostic vision model interface.

Swap between models by changing LLM_PROVIDER + credentials in .env.
No code changes needed.

Supported providers:
    azure_openai  — Azure AI Foundry / Azure OpenAI Service (any deployed model)
    openai        — Standard OpenAI API
    gemini        — Google Gemini (2.5 Flash / Pro)
    anthropic     — Anthropic Claude (Sonnet, Opus)
    groq          — Groq-hosted Llama (Scout, Maverick)
"""

import os
import json
import base64
import httpx
import re
from abc import ABC, abstractmethod
from typing import Optional


# ─────────────────────────────────────────────
#  Shared HTTP Client
# ─────────────────────────────────────────────
_llm_client: Optional[httpx.AsyncClient] = None


def _get_llm_client() -> httpx.AsyncClient:
    """Singleton async HTTP client shared by all LLM providers."""
    global _llm_client
    if _llm_client is None or _llm_client.is_closed:
        _llm_client = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=15.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
    return _llm_client


def _parse_json_from_response(text: str) -> dict:
    """
    Extract a JSON object from an LLM response that may contain markdown fences
    or extra prose around the JSON block.
    """
    # Try to find a ```json ... ``` block first
    json_block = re.search(r'```(?:json)?\s*\n?(.*?)```', text, re.DOTALL)
    if json_block:
        text = json_block.group(1).strip()

    # Try direct JSON parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find the first { ... } block
    brace_match = re.search(r'\{.*\}', text, re.DOTALL)
    if brace_match:
        try:
            return json.loads(brace_match.group(0))
        except json.JSONDecodeError:
            pass

    return {}


def _image_to_data_url(image_bytes: bytes, content_type: str = "image/jpeg") -> str:
    """Convert raw image bytes to a base64 data URL for vision APIs."""
    b64 = base64.b64encode(image_bytes).decode("utf-8")
    # Map common content types
    mime = content_type
    if mime == "application/pdf":
        mime = "application/pdf"
    elif mime not in {"image/jpeg", "image/png", "image/webp", "image/gif"}:
        mime = "image/jpeg"
    return f"data:{mime};base64,{b64}"


# ─────────────────────────────────────────────
#  Abstract Base
# ─────────────────────────────────────────────
class BaseLLMProvider(ABC):
    """
    Abstract base class for all LLM vision providers.
    
    Subclasses must implement:
        extract_from_image(image_bytes, prompt, content_type) -> dict
    """

    @abstractmethod
    async def extract_from_image(
        self,
        image_bytes: bytes,
        prompt: str,
        content_type: str = "image/jpeg",
    ) -> dict:
        """
        Send an image + prompt to the vision LLM and return a parsed JSON dict.
        
        Args:
            image_bytes: Raw bytes of the image (JPEG/PNG) or PDF.
            prompt: The extraction prompt (should request JSON output).
            content_type: MIME type of the image.
            
        Returns:
            Parsed dict from the LLM's JSON response.
        """
        ...

    async def extract_from_text(self, text: str, prompt: str) -> dict:
        """
        Send text + prompt to the LLM and return a parsed JSON dict.
        Default implementation sends the text as a user message (no vision).
        """
        # Subclasses can override if they need a different text-only endpoint
        raise NotImplementedError("Text-only extraction not required for this pipeline.")

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable name for logging."""
        ...


# ─────────────────────────────────────────────
#  Azure AI Foundry / Azure OpenAI Provider
# ─────────────────────────────────────────────
class AzureOpenAIProvider(BaseLLMProvider):
    """
    Azure AI Foundry — Azure OpenAI Service deployment.

    Uses the standard Chat Completions API:
        POST {base_url}/openai/deployments/{model}/chat/completions?api-version={version}
        OR for Azure AI Project endpoint:
        POST {base_url}/openai/v1/chat/completions

    Required .env vars:
        AZURE_OPENAI_KEY          — API key from Azure AI Foundry portal
        AZURE_OPENAI_ENDPOINT     — Base URL: https://<resource>.openai.azure.com or https://...services.ai.azure.com/api/projects/...
        AZURE_OPENAI_MODEL_NAME   — Deployment name (e.g. grok-4.3, gpt-4o)
        AZURE_OPENAI_API_VERSION  — API version (default: 2024-12-01-preview)
    """

    def __init__(self):
        # Support both standard AZURE_OPENAI_* naming and the user-specified Endpoint/Key/Model naming
        # Prioritize explicit Endpoint/Key/Model from the user-modified .env
        self.api_key = (
            os.getenv("Key")
            or os.getenv("KEY")
            or os.getenv("AZURE_OPENAI_KEY")
            or ""
        ).strip().strip('"')

        self.model = (
            os.getenv("Model")
            or os.getenv("MODEL")
            or os.getenv("AZURE_OPENAI_MODEL_NAME")
            or "gpt-4o"
        ).strip().strip('"')

        self.api_version = (
            os.getenv("AZURE_OPENAI_API_VERSION")
            or "2024-12-01-preview"
        ).strip().strip('"')

        self.reasoning_effort = os.getenv("AZURE_OPENAI_REASONING_EFFORT", "").strip()

        # Extract endpoint with fallbacks, prioritizing Endpoint/ENDPOINT
        raw = (
            os.getenv("Endpoint")
            or os.getenv("ENDPOINT")
            or os.getenv("AZURE_OPENAI_ENDPOINT")
            or ""
        ).strip().strip('"').rstrip("/")

        # Check if it is a project-scoped services endpoint
        self.is_project_endpoint = "/api/projects/" in raw

        if self.is_project_endpoint:
            # Keep the project-scoped endpoint path intact
            self.base_url = raw
        else:
            # Strip standard Azure OpenAI paths
            for strip_path in ("/openai/responses", "/openai/deployments", "/openai"):
                if strip_path in raw:
                    raw = raw.split(strip_path)[0]
                    break
            self.base_url = raw

        if not self.api_key or not self.base_url:
            raise ValueError(
                "Azure AI Foundry credentials missing. "
                "Set AZURE_OPENAI_KEY (or Key) and AZURE_OPENAI_ENDPOINT (or Endpoint) in .env"
            )

    @property
    def provider_name(self) -> str:
        return f"Azure AI Foundry ({self.model})"

    def _chat_url(self) -> str:
        """Build the Chat Completions URL for this deployment/project."""
        if self.is_project_endpoint:
            return f"{self.base_url}/openai/v1/chat/completions"
        else:
            return (
                f"{self.base_url}/openai/deployments/{self.model}"
                f"/chat/completions?api-version={self.api_version}"
            )

    def _headers(self) -> dict:
        return {
            "api-key": self.api_key,
            "Content-Type": "application/json",
        }

    async def extract_from_image(
        self, image_bytes: bytes, prompt: str, content_type: str = "image/jpeg"
    ) -> dict:
        client = _get_llm_client()
        data_url = _image_to_data_url(image_bytes, content_type)

        payload = {
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert document data extractor. Always respond with valid JSON only, no extra text.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url, "detail": "high"},
                        },
                    ],
                },
            ],
            "max_tokens": 4096,
            "temperature": 0.1,
        }

        # Include model in the payload for project-scoped inference
        if self.is_project_endpoint:
            payload["model"] = self.model

        response = await client.post(self._chat_url(), headers=self._headers(), json=payload)
        if response.status_code != 200:
            raise RuntimeError(
                f"Azure AI Foundry API error ({response.status_code}): {response.text}"
            )

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return _parse_json_from_response(content)

    async def extract_from_text(self, text: str, prompt: str) -> dict:
        client = _get_llm_client()

        full_prompt = f"{prompt}\n\nDOCUMENT TEXT:\n{text}"

        payload = {
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert document data extractor. Always respond with valid JSON only, no extra text.",
                },
                {
                    "role": "user",
                    "content": full_prompt,
                },
            ],
            "max_tokens": 4096,
            "temperature": 0.1,
        }

        # Include model in the payload for project-scoped inference
        if self.is_project_endpoint:
            payload["model"] = self.model

        response = await client.post(self._chat_url(), headers=self._headers(), json=payload)
        if response.status_code != 200:
            raise RuntimeError(
                f"Azure AI Foundry API error ({response.status_code}): {response.text}"
            )

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return _parse_json_from_response(content)


# ─────────────────────────────────────────────
#  Standard OpenAI Provider
# ─────────────────────────────────────────────
class OpenAIProvider(BaseLLMProvider):
    """
    Standard OpenAI API — uses the Chat Completions API with vision.
    
    Required .env vars:
        OPENAI_API_KEY
        OPENAI_MODEL_NAME (default: gpt-4o)
    """

    def __init__(self):
        self.api_key = os.getenv("OPENAI_API_KEY", "")
        self.model = os.getenv("OPENAI_MODEL_NAME", "gpt-4o")
        self.base_url = os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1")

        if not self.api_key:
            raise ValueError(
                "OpenAI API key missing. Set OPENAI_API_KEY in .env"
            )

    @property
    def provider_name(self) -> str:
        return f"OpenAI ({self.model})"

    async def extract_from_image(
        self, image_bytes: bytes, prompt: str, content_type: str = "image/jpeg"
    ) -> dict:
        client = _get_llm_client()
        data_url = _image_to_data_url(image_bytes, content_type)

        url = f"{self.base_url.rstrip('/')}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert document data extractor. Always respond with valid JSON only, no extra text.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url, "detail": "high"},
                        },
                    ],
                },
            ],
            "max_tokens": 4096,
            "temperature": 0.1,
        }

        response = await client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise RuntimeError(
                f"OpenAI API error ({response.status_code}): {response.text}"
            )

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return _parse_json_from_response(content)

    async def extract_from_text(self, text: str, prompt: str) -> dict:
        client = _get_llm_client()
        url = f"{self.base_url.rstrip('/')}/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        full_prompt = f"{prompt}\n\nDOCUMENT TEXT:\n{text}"

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert document data extractor. Always respond with valid JSON only, no extra text.",
                },
                {
                    "role": "user",
                    "content": full_prompt,
                },
            ],
            "max_tokens": 4096,
            "temperature": 0.1,
        }

        response = await client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise RuntimeError(
                f"OpenAI API error ({response.status_code}): {response.text}"
            )

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return _parse_json_from_response(content)



# ─────────────────────────────────────────────
#  Google Gemini Provider
# ─────────────────────────────────────────────
class GeminiProvider(BaseLLMProvider):
    """
    Google Gemini — uses the generateContent REST API with inline image data.
    
    Required .env vars:
        GEMINI_API_KEY
        GEMINI_MODEL_NAME (default: gemini-2.5-flash)
    """

    def __init__(self):
        self.api_key = os.getenv("GEMINI_API_KEY", "")
        self.model = os.getenv("GEMINI_MODEL_NAME", "gemini-2.5-flash")

        if not self.api_key:
            raise ValueError(
                "Gemini API key missing. Set GEMINI_API_KEY in .env"
            )

    @property
    def provider_name(self) -> str:
        return f"Google Gemini ({self.model})"

    async def extract_from_image(
        self, image_bytes: bytes, prompt: str, content_type: str = "image/jpeg"
    ) -> dict:
        client = _get_llm_client()
        b64_image = base64.b64encode(image_bytes).decode("utf-8")

        # Map content type for Gemini's inlineData
        mime = content_type
        if mime not in {"image/jpeg", "image/png", "image/webp", "image/gif", "application/pdf"}:
            mime = "image/jpeg"

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}"
            f":generateContent?key={self.api_key}"
        )

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                        {
                            "inline_data": {
                                "mime_type": mime,
                                "data": b64_image,
                            }
                        },
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 4096,
                "responseMimeType": "application/json",
            },
        }

        headers = {"Content-Type": "application/json"}
        response = await client.post(url, headers=headers, json=payload)

        if response.status_code != 200:
            raise RuntimeError(
                f"Gemini API error ({response.status_code}): {response.text}"
            )

        data = response.json()
        # Gemini response: candidates[0].content.parts[0].text
        try:
            content = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise RuntimeError(f"Unexpected Gemini response structure: {json.dumps(data)[:500]}")

        return _parse_json_from_response(content)

    async def extract_from_text(self, text: str, prompt: str) -> dict:
        client = _get_llm_client()
        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}"
            f":generateContent?key={self.api_key}"
        )

        full_prompt = f"{prompt}\n\nDOCUMENT TEXT:\n{text}"

        payload = {
            "contents": [
                {
                    "parts": [
                        {"text": full_prompt}
                    ]
                }
            ],
            "generationConfig": {
                "temperature": 0.1,
                "maxOutputTokens": 4096,
                "responseMimeType": "application/json",
            },
        }

        headers = {"Content-Type": "application/json"}
        response = await client.post(url, headers=headers, json=payload)

        if response.status_code != 200:
            raise RuntimeError(
                f"Gemini API error ({response.status_code}): {response.text}"
            )

        data = response.json()
        try:
            content = data["candidates"][0]["content"]["parts"][0]["text"]
        except (KeyError, IndexError):
            raise RuntimeError(f"Unexpected Gemini response structure: {json.dumps(data)[:500]}")

        return _parse_json_from_response(content)



# ─────────────────────────────────────────────
#  Anthropic Claude Provider
# ─────────────────────────────────────────────
class AnthropicProvider(BaseLLMProvider):
    """
    Anthropic Claude — uses the Messages API with vision.
    
    Required .env vars:
        ANTHROPIC_API_KEY
        ANTHROPIC_MODEL_NAME (default: claude-sonnet-4-20250514)
    """

    def __init__(self):
        self.api_key = os.getenv("ANTHROPIC_API_KEY", "")
        self.model = os.getenv("ANTHROPIC_MODEL_NAME", "claude-sonnet-4-20250514")

        if not self.api_key:
            raise ValueError(
                "Anthropic API key missing. Set ANTHROPIC_API_KEY in .env"
            )

    @property
    def provider_name(self) -> str:
        return f"Anthropic Claude ({self.model})"

    async def extract_from_image(
        self, image_bytes: bytes, prompt: str, content_type: str = "image/jpeg"
    ) -> dict:
        client = _get_llm_client()
        b64_image = base64.b64encode(image_bytes).decode("utf-8")

        # Claude supports image/jpeg, image/png, image/gif, image/webp
        media_type = content_type
        if media_type not in {"image/jpeg", "image/png", "image/gif", "image/webp"}:
            media_type = "image/jpeg"

        url = "https://api.anthropic.com/v1/messages"

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": 0.1,
            "system": "You are an expert document data extractor. Always respond with valid JSON only, no extra text.",
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": b64_image,
                            },
                        },
                        {"type": "text", "text": prompt},
                    ],
                }
            ],
        }

        response = await client.post(url, headers=headers, json=payload)

        if response.status_code != 200:
            raise RuntimeError(
                f"Anthropic API error ({response.status_code}): {response.text}"
            )

        data = response.json()
        # Claude response: content[0].text
        try:
            content = data["content"][0]["text"]
        except (KeyError, IndexError):
            raise RuntimeError(f"Unexpected Anthropic response structure: {json.dumps(data)[:500]}")

        return _parse_json_from_response(content)

    async def extract_from_text(self, text: str, prompt: str) -> dict:
        client = _get_llm_client()
        url = "https://api.anthropic.com/v1/messages"

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        }

        full_prompt = f"{prompt}\n\nDOCUMENT TEXT:\n{text}"

        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": 0.1,
            "system": "You are an expert document data extractor. Always respond with valid JSON only, no extra text.",
            "messages": [
                {
                    "role": "user",
                    "content": full_prompt,
                }
            ],
        }

        response = await client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise RuntimeError(
                f"Anthropic API error ({response.status_code}): {response.text}"
            )

        data = response.json()
        try:
            content = data["content"][0]["text"]
        except (KeyError, IndexError):
            raise RuntimeError(f"Unexpected Anthropic response structure: {json.dumps(data)[:500]}")

        return _parse_json_from_response(content)



# ─────────────────────────────────────────────
#  Groq Provider (Llama Vision)
# ─────────────────────────────────────────────
class GroqProvider(BaseLLMProvider):
    """
    Groq — hosts Llama models with vision capabilities.
    Uses the OpenAI-compatible Chat Completions API.
    
    Required .env vars:
        GROQ_API_KEY
        GROQ_MODEL_NAME (default: llama-4-scout-17b-16e-instruct)
    """

    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY", "")
        self.model = os.getenv("GROQ_MODEL_NAME", "llama-4-scout-17b-16e-instruct")

        if not self.api_key:
            raise ValueError(
                "Groq API key missing. Set GROQ_API_KEY in .env"
            )

    @property
    def provider_name(self) -> str:
        return f"Groq Llama ({self.model})"

    async def extract_from_image(
        self, image_bytes: bytes, prompt: str, content_type: str = "image/jpeg"
    ) -> dict:
        client = _get_llm_client()
        data_url = _image_to_data_url(image_bytes, content_type)

        url = "https://api.groq.com/openai/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert document data extractor. Always respond with valid JSON only, no extra text.",
                },
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": data_url},
                        },
                    ],
                },
            ],
            "max_tokens": 4096,
            "temperature": 0.1,
        }

        response = await client.post(url, headers=headers, json=payload)

        if response.status_code != 200:
            raise RuntimeError(
                f"Groq API error ({response.status_code}): {response.text}"
            )

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return _parse_json_from_response(content)

    async def extract_from_text(self, text: str, prompt: str) -> dict:
        client = _get_llm_client()
        url = "https://api.groq.com/openai/v1/chat/completions"

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        full_prompt = f"{prompt}\n\nDOCUMENT TEXT:\n{text}"

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": "You are an expert document data extractor. Always respond with valid JSON only, no extra text.",
                },
                {
                    "role": "user",
                    "content": full_prompt,
                },
            ],
            "max_tokens": 4096,
            "temperature": 0.1,
        }

        response = await client.post(url, headers=headers, json=payload)
        if response.status_code != 200:
            raise RuntimeError(
                f"Groq API error ({response.status_code}): {response.text}"
            )

        data = response.json()
        content = data["choices"][0]["message"]["content"]
        return _parse_json_from_response(content)



# ─────────────────────────────────────────────
#  Provider Factory
# ─────────────────────────────────────────────
_PROVIDER_MAP = {
    "azure_openai": AzureOpenAIProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "anthropic": AnthropicProvider,
    "groq": GroqProvider,
}

# Cache the provider instance so we don't re-create on every request
_cached_provider: Optional[BaseLLMProvider] = None
_cached_provider_name: Optional[str] = None


def get_llm_provider() -> BaseLLMProvider:
    """
    Factory: returns the LLM provider configured by LLM_PROVIDER in .env.
    
    To switch models, change these .env values and restart:
        LLM_PROVIDER=gemini
        GEMINI_API_KEY=AIza...
        GEMINI_MODEL_NAME=gemini-2.5-flash
    
    The provider instance is cached for the lifetime of the process.
    """
    global _cached_provider, _cached_provider_name

    provider_key = os.getenv("LLM_PROVIDER", "azure_openai").lower().strip()

    # Return cached if the provider hasn't changed and settings match the environment
    if _cached_provider is not None and _cached_provider_name == provider_key:
        current_model = (
            os.getenv("Model")
            or os.getenv("MODEL")
            or os.getenv("AZURE_OPENAI_MODEL_NAME")
            or os.getenv("OPENAI_MODEL_NAME")
            or os.getenv("GEMINI_MODEL_NAME")
            or os.getenv("ANTHROPIC_MODEL_NAME")
            or os.getenv("GROQ_MODEL_NAME")
            or ""
        ).strip().strip('"')
        current_key = (
            os.getenv("Key")
            or os.getenv("KEY")
            or os.getenv("AZURE_OPENAI_KEY")
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("GEMINI_API_KEY")
            or os.getenv("ANTHROPIC_API_KEY")
            or os.getenv("GROQ_API_KEY")
            or ""
        ).strip().strip('"')
        
        cached_model = getattr(_cached_provider, "model", "")
        cached_key = getattr(_cached_provider, "api_key", "")
        if cached_key == current_key and (not current_model or cached_model == current_model):
            return _cached_provider

    if provider_key not in _PROVIDER_MAP:
        available = ", ".join(sorted(_PROVIDER_MAP.keys()))
        raise ValueError(
            f"Unknown LLM_PROVIDER='{provider_key}'. "
            f"Available providers: {available}"
        )

    print(f"[LLM] Initializing provider: {provider_key}")
    _cached_provider = _PROVIDER_MAP[provider_key]()
    _cached_provider_name = provider_key
    print(f"[LLM] Provider ready: {_cached_provider.provider_name}")

    return _cached_provider
