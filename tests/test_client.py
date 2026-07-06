"""Tests for CortexSTTClient."""

import asyncio
import json
import re
from collections.abc import AsyncIterator

import aiohttp
import pytest
from aiohttp import web
from aiohttp.test_utils import TestServer
from aioresponses import aioresponses

from custom_components.cortex_stt import client as client_module
from custom_components.cortex_stt.client import (
    CortexSTTClient,
    CortexSTTStreamConnectError,
    CortexSTTStreamError,
)
from custom_components.cortex_stt.models import (
    EngineStatus,
    ModelInfo,
    TranscribeResult,
)

BASE_URL = "http://localhost:8769"


@pytest.fixture
def mock_aiohttp():
    with aioresponses() as m:
        yield m


@pytest.fixture
async def client(mock_aiohttp):
    session = aiohttp.ClientSession()
    c = CortexSTTClient(host=BASE_URL, api_key="test-key", session=session)
    yield c
    await session.close()


# ── health ──


async def test_health_success(mock_aiohttp, client):
    """GET /health returns JSON dict."""
    payload = {"status": "ok", "version": "1.2.3"}
    mock_aiohttp.get(f"{BASE_URL}/health", payload=payload)

    result = await client.health()

    assert result == payload


# ── validate ──


async def test_validate_success(mock_aiohttp, client):
    """Validate returns None when health and engine both succeed."""
    mock_aiohttp.get(f"{BASE_URL}/health", payload={"status": "ok"})
    mock_aiohttp.get(
        f"{BASE_URL}/api/engine", payload={"loaded_models": [], "loaded_count": 0}
    )

    result = await client.validate()

    assert result is None


async def test_validate_cannot_connect(mock_aiohttp, client):
    """Validate returns 'cannot_connect' when health raises ClientError."""
    mock_aiohttp.get(f"{BASE_URL}/health", exception=aiohttp.ClientError())

    result = await client.validate()

    assert result == "cannot_connect"


async def test_validate_timeout(mock_aiohttp, client):
    """Validate returns 'cannot_connect' when health raises TimeoutError."""
    mock_aiohttp.get(f"{BASE_URL}/health", exception=TimeoutError())

    result = await client.validate()

    assert result == "cannot_connect"


async def test_validate_invalid_api_key(mock_aiohttp, client):
    """Validate returns 'invalid_api_key' when engine returns 401."""
    mock_aiohttp.get(f"{BASE_URL}/health", payload={"status": "ok"})
    mock_aiohttp.get(f"{BASE_URL}/api/engine", status=401)

    result = await client.validate()

    assert result == "invalid_api_key"


async def test_validate_invalid_api_key_403(mock_aiohttp, client):
    """Validate returns 'invalid_api_key' when engine returns 403."""
    mock_aiohttp.get(f"{BASE_URL}/health", payload={"status": "ok"})
    mock_aiohttp.get(f"{BASE_URL}/api/engine", status=403)

    result = await client.validate()

    assert result == "invalid_api_key"


async def test_validate_engine_connection_error(mock_aiohttp, client):
    """Validate returns 'cannot_connect' when engine raises ClientError."""
    mock_aiohttp.get(f"{BASE_URL}/health", payload={"status": "ok"})
    mock_aiohttp.get(f"{BASE_URL}/api/engine", exception=aiohttp.ClientError())

    result = await client.validate()

    assert result == "cannot_connect"


# ── list_models ──


async def test_list_models(mock_aiohttp, client):
    """GET /api/models parses ModelInfo list with defaults for missing fields."""
    mock_aiohttp.get(
        f"{BASE_URL}/api/models",
        payload=[
            {
                "id": "whisper-large-v3",
                "name": "Whisper Large V3",
                "description": "OpenAI Whisper",
                "status": "downloaded",
                "size_mb": 3000,
                "languages": ["en", "zh"],
                "is_loaded": True,
                "recommended": True,
            },
            {
                "id": "parakeet-tdt-0.6b-v3",
                "name": "Parakeet TDT 0.6B v3",
                # Missing optional fields -- should use defaults
            },
        ],
    )

    models = await client.list_models()

    assert len(models) == 2

    m0 = models[0]
    assert isinstance(m0, ModelInfo)
    assert m0.id == "whisper-large-v3"
    assert m0.name == "Whisper Large V3"
    assert m0.description == "OpenAI Whisper"
    assert m0.status == "downloaded"
    assert m0.size_mb == 3000
    assert m0.languages == ["en", "zh"]
    assert m0.is_loaded is True
    assert m0.recommended is True

    m1 = models[1]
    assert m1.id == "parakeet-tdt-0.6b-v3"
    assert m1.name == "Parakeet TDT 0.6B v3"
    assert m1.description == ""
    assert m1.status == "unknown"
    assert m1.size_mb == 0
    assert m1.languages == []
    assert m1.is_loaded is False
    assert m1.recommended is False


async def test_list_models_reads_legacy_0_2_x_fields(mock_aiohttp, client):
    """A 0.2.x addon (supported_languages/is_recommended) still parses."""
    mock_aiohttp.get(
        f"{BASE_URL}/api/models",
        payload=[
            {
                "id": "whisper-small",
                "name": "Whisper Small",
                "status": "downloaded",
                "supported_languages": ["en", "zh"],
                "is_recommended": True,
            }
        ],
    )

    models = await client.list_models()

    assert models[0].languages == ["en", "zh"]
    assert models[0].recommended is True


# ── engine_status ──


async def test_engine_status(mock_aiohttp, client):
    """GET /api/engine parses EngineStatus."""
    mock_aiohttp.get(
        f"{BASE_URL}/api/engine",
        payload={"loaded_models": ["whisper-large-v3"], "loaded_count": 1},
    )

    status = await client.engine_status()

    assert isinstance(status, EngineStatus)
    assert status.loaded_models == ["whisper-large-v3"]
    assert status.loaded_count == 1


# ── transcribe ──


async def test_transcribe_success(mock_aiohttp, client):
    """POST /api/transcribe parses TranscribeResult."""
    mock_aiohttp.post(
        re.compile(r"^http://localhost:8769/api/transcribe"),
        payload={
            "text": "hello world",
            "model": "whisper-large-v3",
            "duration_ms": 1500,
            "inference_ms": 200,
            "segments": [{"start": 0, "end": 1.5, "text": "hello world"}],
        },
    )

    result = await client.transcribe(
        audio_data=b"\x00" * 100,
        model_id="whisper-large-v3",
        language="en",
    )

    assert isinstance(result, TranscribeResult)
    assert result.text == "hello world"
    assert result.model == "whisper-large-v3"
    assert result.duration_ms == 1500
    assert result.inference_ms == 200
    assert len(result.segments) == 1


async def test_transcribe_with_correct_params(mock_aiohttp, client):
    """POST /api/transcribe sends model, language, sample_rate, channels as query params."""
    mock_aiohttp.post(
        re.compile(r"^http://localhost:8769/api/transcribe"),
        payload={
            "text": "test",
            "model": "parakeet",
            "duration_ms": 0,
            "inference_ms": 0,
            "segments": [],
        },
    )

    await client.transcribe(
        audio_data=b"\x00" * 10,
        model_id="parakeet",
        language="zh",
    )

    # aioresponses records calls -- inspect the last request
    history = mock_aiohttp.requests
    # Find the POST to /api/transcribe
    post_calls = [
        (key, calls)
        for key, calls in history.items()
        if key[0] == "POST" and "/api/transcribe" in str(key[1])
    ]
    assert len(post_calls) == 1
    url = post_calls[0][0][1]
    query = url.query

    assert query["model"] == "parakeet"
    assert query["language"] == "zh"
    assert query["sample_rate"] == "16000"
    assert query["channels"] == "1"


# ── headers ──


async def test_headers_contain_bearer_token(mock_aiohttp, client):
    """Authenticated requests include Authorization: Bearer <api_key>."""
    mock_aiohttp.get(
        f"{BASE_URL}/api/engine",
        payload={"loaded_models": [], "loaded_count": 0},
    )

    await client.engine_status()

    # Inspect the request that was made
    history = mock_aiohttp.requests
    get_calls = [
        (key, calls)
        for key, calls in history.items()
        if key[0] == "GET" and "/api/engine" in str(key[1])
    ]
    assert len(get_calls) == 1
    request_kwargs = get_calls[0][1][0].kwargs
    assert request_kwargs["headers"]["Authorization"] == "Bearer test-key"


# ── transcribe_stream (real WebSocket test server) ──
#
# aioresponses does not support WebSockets, so these tests spin up a real
# aiohttp server exposing /api/transcribe/stream that speaks the protocol.
# The protocol is ready-gated: the client sends `start` and blocks until the
# server's `ready` event before it feeds any audio.


async def _audio_stream(chunks: list[bytes]) -> AsyncIterator[bytes]:
    """Yield audio chunks as an async iterable."""
    for chunk in chunks:
        yield chunk


async def _slow_stream(
    chunks: list[bytes], delay: float = 0.01
) -> AsyncIterator[bytes]:
    """Yield audio chunks with a small delay so the reader task can interleave."""
    for chunk in chunks:
        yield chunk
        await asyncio.sleep(delay)


async def _start_ws_server(handler) -> TestServer:
    """Start a TestServer exposing the streaming route with the given handler."""
    app = web.Application()
    app.router.add_get("/api/transcribe/stream", handler)
    server = TestServer(app)
    await server.start_server()
    return server


def _client_for(server: TestServer, session: aiohttp.ClientSession) -> CortexSTTClient:
    return CortexSTTClient(
        host=f"http://127.0.0.1:{server.port}", api_key="test-key", session=session
    )


async def test_transcribe_stream_happy_path():
    """ready -> partial (ignored) -> final yields a TranscribeResult."""
    received_binary: list[bytes] = []
    start_msg: dict = {}
    auth_header: dict = {}

    async def handler(request):
        # Auth arrives via the Bearer header, never the URL query (no key leak).
        auth_header["value"] = request.headers.get("Authorization")
        auth_header["has_query_key"] = "api_key" in request.query
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("type") == "start":
                    start_msg.update(data)
                    await ws.send_json({"type": "ready", "streaming": True})
                    await ws.send_json({"type": "partial", "text": "he", "revision": 0})
                elif data.get("type") == "finalize":
                    await ws.send_json(
                        {
                            "type": "final",
                            "text": "hello world",
                            "model": "whisper-small",
                            "duration_ms": 100,
                            "inference_ms": 80,
                            "segments": [{"start": 0, "end": 1.5, "text": "hello"}],
                            "language": "en",
                        }
                    )
                    await ws.close()
            elif msg.type == aiohttp.WSMsgType.BINARY:
                received_binary.append(msg.data)
        return ws

    server = await _start_ws_server(handler)
    session = aiohttp.ClientSession()
    try:
        client = _client_for(server, session)
        result = await client.transcribe_stream(
            _audio_stream([b"\x00" * 320, b"\x11" * 320]),
            model_id="whisper-small",
            language="en",
        )

        assert isinstance(result, TranscribeResult)
        assert result.text == "hello world"
        assert result.model == "whisper-small"
        assert result.duration_ms == 100
        assert result.inference_ms == 80
        assert len(result.segments) == 1
        # Auth via header only -- the API key must not be in the URL.
        assert auth_header["value"] == "Bearer test-key"
        assert auth_header["has_query_key"] is False
        # start control message carried the expected fields
        assert start_msg["model"] == "whisper-small"
        assert start_msg["language"] == "en"
        assert start_msg["format"] == "pcm_s16le"
        assert start_msg["sample_rate"] == 16000
        assert start_msg["channels"] == 1
        # audio chunks arrived as binary frames, in order
        assert received_binary == [b"\x00" * 320, b"\x11" * 320]
    finally:
        await session.close()
        await server.close()


async def test_transcribe_stream_omits_empty_language():
    """A blank language is not sent in the start message."""
    start_msg: dict = {}

    async def handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("type") == "start":
                    start_msg.update(data)
                    await ws.send_json({"type": "ready", "streaming": False})
                elif data.get("type") == "finalize":
                    await ws.send_json({"type": "final", "text": "ok"})
                    await ws.close()
        return ws

    server = await _start_ws_server(handler)
    session = aiohttp.ClientSession()
    try:
        client = _client_for(server, session)
        await client.transcribe_stream(
            _audio_stream([b"\x00" * 10]), model_id="whisper-small", language=""
        )
        assert "language" not in start_msg
    finally:
        await session.close()
        await server.close()


async def test_transcribe_stream_handshake_error_is_connect_error():
    """An error BEFORE ready is fallback-eligible (CortexSTTStreamConnectError)."""

    async def handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("type") == "start":
                    # Server-side handshake failure (e.g. model missing) arrives
                    # before ready and closes the socket.
                    await ws.send_json(
                        {
                            "type": "error",
                            "code": "MODEL_NOT_FOUND",
                            "message": "no such model",
                            "model_id": "whisper-small",
                        }
                    )
                    await ws.close()
        return ws

    server = await _start_ws_server(handler)
    session = aiohttp.ClientSession()
    try:
        client = _client_for(server, session)
        with pytest.raises(CortexSTTStreamConnectError) as exc_info:
            await client.transcribe_stream(
                _audio_stream([b"\x00" * 10]),
                model_id="whisper-small",
                language="en",
            )
        # Carries the server code, but never the URL/key.
        assert exc_info.value.code == "MODEL_NOT_FOUND"
        assert "api_key" not in str(exc_info.value)
        assert "127.0.0.1" not in str(exc_info.value)
    finally:
        await session.close()
        await server.close()


async def test_transcribe_stream_handshake_timeout_is_connect_error(monkeypatch):
    """No ready within the handshake window -> CortexSTTStreamConnectError."""
    monkeypatch.setattr(client_module, "_HANDSHAKE_TIMEOUT", 0.2)

    async def handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        # Read the start message but never send ready (blackhole).
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.CLOSE:
                break
        return ws

    server = await _start_ws_server(handler)
    session = aiohttp.ClientSession()
    try:
        client = _client_for(server, session)
        with pytest.raises(CortexSTTStreamConnectError):
            await client.transcribe_stream(
                _audio_stream([b"\x00" * 10]),
                model_id="whisper-small",
                language="en",
            )
    finally:
        await session.close()
        await server.close()


async def test_transcribe_stream_post_ready_error_event():
    """An error AFTER ready raises CortexSTTStreamError (not fallback-eligible)."""

    async def handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("type") == "start":
                    await ws.send_json({"type": "ready", "streaming": True})
                elif data.get("type") == "finalize":
                    await ws.send_json(
                        {
                            "type": "error",
                            "code": "INFERENCE_FAILED",
                            "message": "boom",
                            "model_id": "whisper-small",
                        }
                    )
                    await ws.close()
        return ws

    server = await _start_ws_server(handler)
    session = aiohttp.ClientSession()
    try:
        client = _client_for(server, session)
        with pytest.raises(CortexSTTStreamError) as exc_info:
            await client.transcribe_stream(
                _audio_stream([b"\x00" * 10]),
                model_id="whisper-small",
                language="en",
            )
        assert exc_info.value.code == "INFERENCE_FAILED"
        assert exc_info.value.model_id == "whisper-small"
    finally:
        await session.close()
        await server.close()


async def test_transcribe_stream_mid_stream_error_stops_feeding():
    """A mid-stream error is seen at once and the client stops feeding audio."""
    received_binary: list[bytes] = []

    async def handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("type") == "start":
                    await ws.send_json({"type": "ready", "streaming": True})
            elif msg.type == aiohttp.WSMsgType.BINARY:
                received_binary.append(msg.data)
                # Fail on the first audio frame.
                await ws.send_json(
                    {"type": "error", "code": "INFERENCE_FAILED", "message": "boom"}
                )
                await ws.close()
                break
        return ws

    server = await _start_ws_server(handler)
    session = aiohttp.ClientSession()
    try:
        client = _client_for(server, session)
        with pytest.raises(CortexSTTStreamError):
            await client.transcribe_stream(
                _slow_stream([b"\x00" * 320] * 20),
                model_id="whisper-small",
                language="en",
            )
        # Feeding stopped well before all 20 chunks were sent.
        assert len(received_binary) < 20
    finally:
        await session.close()
        await server.close()


async def test_transcribe_stream_closed_before_final():
    """A close after ready but before final raises CortexSTTStreamError."""

    async def handler(request):
        ws = web.WebSocketResponse()
        await ws.prepare(request)
        async for msg in ws:
            if msg.type == aiohttp.WSMsgType.TEXT:
                data = json.loads(msg.data)
                if data.get("type") == "start":
                    await ws.send_json({"type": "ready", "streaming": True})
                elif data.get("type") == "finalize":
                    await ws.close()
        return ws

    server = await _start_ws_server(handler)
    session = aiohttp.ClientSession()
    try:
        client = _client_for(server, session)
        with pytest.raises(CortexSTTStreamError):
            await client.transcribe_stream(
                _audio_stream([b"\x00" * 10]),
                model_id="whisper-small",
                language="en",
            )
    finally:
        await session.close()
        await server.close()


async def test_transcribe_stream_connect_failure():
    """A failed WS connect raises CortexSTTStreamConnectError (fallback signal)."""
    session = aiohttp.ClientSession()
    try:
        # Port 1 is not listening -> connect refused.
        client = CortexSTTClient(
            host="http://127.0.0.1:1", api_key="test-key", session=session
        )
        with pytest.raises(CortexSTTStreamConnectError) as exc_info:
            await client.transcribe_stream(
                _audio_stream([b"\x00" * 10]),
                model_id="whisper-small",
                language="en",
            )
        # Connect-failure message must not leak the URL/key.
        assert "api_key" not in str(exc_info.value)
    finally:
        await session.close()
