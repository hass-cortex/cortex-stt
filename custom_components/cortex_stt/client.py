"""HTTP client for Cortex STT API."""

from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterable
from typing import Any

import aiohttp

from .models import EngineStatus, ModelInfo, TranscribeResult

_LOGGER = logging.getLogger(__name__)


_API_TIMEOUT = aiohttp.ClientTimeout(total=10)
# Bound the connect -> start -> ready handshake; on timeout the caller may
# fall back to the sync POST endpoint (matches _API_TIMEOUT semantics).
_HANDSHAKE_TIMEOUT = 10
_TRANSCRIBE_TIMEOUT = aiohttp.ClientTimeout(total=300)


class CortexSTTStreamError(aiohttp.ClientError):
    """Server returned an error event during streaming transcription."""

    def __init__(
        self, message: str, *, code: str | None = None, model_id: str | None = None
    ) -> None:
        """Initialize with the server-provided error code and model id."""
        super().__init__(message)
        self.code = code
        self.model_id = model_id


class CortexSTTStreamConnectError(aiohttp.ClientError):
    """WebSocket connect/handshake failed before ready.

    Signals the handshake never completed (connect refused, timeout, or an
    error/close before the ``ready`` event), so the caller may fall back to
    the sync POST endpoint. Carries the server ``code`` when one was received;
    never carries the connection URL (which holds no secret anyway).
    """

    def __init__(self, message: str, *, code: str | None = None) -> None:
        """Initialize with an optional server-provided error code."""
        super().__init__(message)
        self.code = code


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
                status=m.get("status", "unknown"),
                size_mb=m.get("size_mb", 0),
                # Fall back to 0.2.x field names against an older addon so a
                # mixed-version window does not blank out language matching.
                languages=m.get("languages") or m.get("supported_languages") or [],
                is_loaded=m.get("is_loaded", False),
                recommended=m.get("recommended", m.get("is_recommended", False)),
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

    async def transcribe_stream(
        self,
        audio_stream: AsyncIterable[bytes],
        model_id: str,
        language: str,
    ) -> TranscribeResult:
        """Transcribe a live audio stream over the WebSocket endpoint.

        Opens ``/api/transcribe/stream``, sends a ``start`` control message and
        waits for the server's ``ready`` event (the handshake). Only after
        ``ready`` does it forward PCM16LE chunks as binary frames while a reader
        consumes events concurrently, so a mid-stream server error stops feeding
        immediately. Sends ``finalize`` and returns the terminal ``final`` event.

        Auth uses the Bearer header (accepted on WS by the server middleware) so
        the API key never appears in the URL and cannot leak through error logs.

        Args:
            audio_stream: Async iterable of raw PCM16LE 16kHz mono chunks.
            model_id: Model ID to use for transcription.
            language: BCP-47 language code (sent only when non-empty).

        Returns:
            TranscribeResult with text and timing information.

        Raises:
            CortexSTTStreamConnectError: The handshake never completed (connect
                refused, timeout, or an error/close before ``ready``); the
                caller may fall back to the sync POST endpoint.
            CortexSTTStreamError: A post-ready server error or a socket close
                before a final result.
        """
        ws_url = f"{self._host}/api/transcribe/stream"
        start: dict[str, Any] = {
            "type": "start",
            "model": model_id,
            "format": "pcm_s16le",
            "sample_rate": 16000,
            "channels": 1,
        }
        if language:
            start["language"] = language

        # ── Connect (fallback-eligible; never surface the URL) ──
        try:
            ws_ctx = self._session.ws_connect(ws_url, headers=self._headers)
            ws = await ws_ctx.__aenter__()
        except aiohttp.ClientError as err:
            raise CortexSTTStreamConnectError("stream connect failed") from err

        try:
            # ── Handshake: send start + await ready, bounded (fallback-eligible) ──
            try:
                async with asyncio.timeout(_HANDSHAKE_TIMEOUT):
                    await self._await_ready(ws, start)
            except TimeoutError as err:
                raise CortexSTTStreamConnectError("stream handshake timed out") from err
            except CortexSTTStreamError as err:
                raise CortexSTTStreamConnectError(
                    f"stream handshake rejected: {err}", code=err.code
                ) from err

            # ── Post-ready: feed audio + read events concurrently ──
            return await self._feed_and_collect(ws, audio_stream, model_id)
        finally:
            await ws_ctx.__aexit__(None, None, None)

    async def _await_ready(
        self, ws: aiohttp.ClientWebSocketResponse, start: dict[str, Any]
    ) -> None:
        """Send the start message and block until the ``ready`` event.

        Raises CortexSTTStreamError if the server emits an error event or closes
        the socket before ``ready`` (server-side handshake failures land here).
        """
        await ws.send_json(start)
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                event = msg.json()
                event_type = event.get("type")
                if event_type == "ready":
                    return
                if event_type == "error":
                    raise CortexSTTStreamError(
                        event.get("message", "stream handshake error"),
                        code=event.get("code"),
                        model_id=event.get("model_id"),
                    )
                # Ignore any stray event before ready.
            elif msg.type == aiohttp.WSMsgType.ERROR:
                raise CortexSTTStreamError(f"websocket error: {ws.exception()}")
            elif msg.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.CLOSED,
            ):
                break
        raise CortexSTTStreamError("socket closed before ready")

    async def _feed_and_collect(
        self,
        ws: aiohttp.ClientWebSocketResponse,
        audio_stream: AsyncIterable[bytes],
        model_id: str,
    ) -> TranscribeResult:
        """Feed audio frames while a reader task consumes events, return final.

        The reader runs concurrently so a server error mid-utterance is seen at
        once; the feed loop stops early when the reader completes. The
        finalize -> final wait is bounded by _TRANSCRIBE_TIMEOUT.
        """
        reader = asyncio.create_task(self._read_until_final(ws, model_id))
        try:
            async for chunk in audio_stream:
                if reader.done():
                    # Server ended early (error/final): stop feeding a dead socket.
                    break
                try:
                    await ws.send_bytes(chunk)
                except (ConnectionError, aiohttp.ClientError):  # fmt: skip
                    # Peer closed mid-feed; the reader holds the real outcome.
                    break
            if not reader.done():
                with contextlib.suppress(ConnectionError, aiohttp.ClientError):
                    await ws.send_json({"type": "finalize"})
            async with asyncio.timeout(_TRANSCRIBE_TIMEOUT.total):
                return await reader
        finally:
            if not reader.done():
                reader.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await reader

    async def _read_until_final(
        self, ws: aiohttp.ClientWebSocketResponse, model_id: str
    ) -> TranscribeResult:
        """Read events until ``final``; ``partial`` ignored, ``error`` raises."""
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                event = msg.json()
                event_type = event.get("type")
                if event_type == "final":
                    return TranscribeResult(
                        text=event.get("text", ""),
                        model=event.get("model", model_id),
                        duration_ms=event.get("duration_ms", 0),
                        inference_ms=event.get("inference_ms", 0),
                        segments=event.get("segments", []),
                    )
                if event_type == "error":
                    raise CortexSTTStreamError(
                        event.get("message", "stream transcription error"),
                        code=event.get("code"),
                        model_id=event.get("model_id"),
                    )
                # Ignore "partial" (and any stray "ready") events.
            elif msg.type == aiohttp.WSMsgType.ERROR:
                raise CortexSTTStreamError(f"websocket error: {ws.exception()}")
            elif msg.type in (
                aiohttp.WSMsgType.CLOSE,
                aiohttp.WSMsgType.CLOSING,
                aiohttp.WSMsgType.CLOSED,
            ):
                break
        raise CortexSTTStreamError("stream closed before final result")
