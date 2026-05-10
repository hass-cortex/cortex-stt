"""HTTP client for Cortex STT API."""

from __future__ import annotations

import logging
from typing import Any

import aiohttp

from .models import EngineStatus, ModelInfo, TranscribeResult

_LOGGER = logging.getLogger(__name__)


_API_TIMEOUT = aiohttp.ClientTimeout(total=10)
_TRANSCRIBE_TIMEOUT = aiohttp.ClientTimeout(total=300)


class CortexSTTClient:
    """Async HTTP client for Cortex STT."""

    def __init__(self, host: str, api_key: str, session: aiohttp.ClientSession) -> None:
        """Initialize the client.

        Args:
            host: Base URL of the Cortex STT app (e.g. http://host:8769).
            api_key: Bearer token for API authentication.
            session: HA shared aiohttp session.
        """
        self._host = host.rstrip("/")
        self._api_key = api_key
        self._session = session

    @property
    def _headers(self) -> dict[str, str]:
        """Return authorization headers for API requests."""
        return {"Authorization": f"Bearer {self._api_key}"}

    async def health(self) -> dict[str, Any]:
        """Check server health (no auth required).

        Returns:
            Health response dict with status, version, etc.
        """
        async with self._session.get(
            f"{self._host}/health",
            timeout=_API_TIMEOUT,
        ) as resp:
            resp.raise_for_status()
            return await resp.json()

    async def validate(self) -> str | None:
        """Validate connectivity and authentication.

        Returns:
            None if valid, or an error string ("cannot_connect" or "invalid_api_key").
        """
        try:
            await self.health()
        except (aiohttp.ClientError, TimeoutError):  # fmt: skip
            return "cannot_connect"

        try:
            async with self._session.get(
                f"{self._host}/api/engine",
                headers=self._headers,
                timeout=_API_TIMEOUT,
            ) as resp:
                if resp.status in (401, 403):
                    return "invalid_api_key"
                resp.raise_for_status()
        except (aiohttp.ClientError, TimeoutError):  # fmt: skip
            return "cannot_connect"

        return None

    async def list_models(self) -> list[ModelInfo]:
        """List all models with their download/load status.

        Returns:
            List of ModelInfo objects from GET /api/models.
        """
        async with self._session.get(
            f"{self._host}/api/models",
            headers=self._headers,
            timeout=_API_TIMEOUT,
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

        return [
            ModelInfo(
                id=m["id"],
                name=m["name"],
                description=m.get("description", ""),
                engine_type=m.get("engine_type", ""),
                status=m.get("status", "unknown"),
                size_mb=m.get("size_mb", 0),
                supported_languages=m.get("supported_languages", []),
                is_loaded=m.get("is_loaded", False),
                is_recommended=m.get("is_recommended", False),
            )
            for m in data
        ]

    async def engine_status(self) -> EngineStatus:
        """Get current engine status with loaded models.

        Returns:
            EngineStatus from GET /api/engine.
        """
        async with self._session.get(
            f"{self._host}/api/engine",
            headers=self._headers,
            timeout=_API_TIMEOUT,
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

        return EngineStatus(
            loaded_models=data.get("loaded_models", []),
            loaded_count=data.get("loaded_count", 0),
        )

    async def transcribe(
        self, audio_data: bytes, model_id: str, language: str
    ) -> TranscribeResult:
        """Transcribe audio using a specific model.

        Args:
            audio_data: Raw WAV audio bytes.
            model_id: Model ID to use for transcription.
            language: BCP-47 language code.

        Returns:
            TranscribeResult with text and timing information.
        """
        params = {
            "model": model_id,
            "language": language,
            "sample_rate": "16000",
            "channels": "1",
        }
        async with self._session.post(
            f"{self._host}/api/transcribe",
            headers={**self._headers, "Content-Type": "application/octet-stream"},
            params=params,
            data=audio_data,
            timeout=_TRANSCRIBE_TIMEOUT,
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()

        return TranscribeResult(
            text=data.get("text", ""),
            model=data.get("model", model_id),
            duration_ms=data.get("duration_ms", 0),
            inference_ms=data.get("inference_ms", 0),
            segments=data.get("segments", []),
        )
