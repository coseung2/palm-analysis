import asyncio
import io
import json

import httpx
import pytest
from PIL import Image

from palm_backend.config import Settings
from palm_backend.errors import ProviderError
from palm_backend.images import prepare_image
from palm_backend.models import BoothConfig
from palm_backend.providers import DemoAnalyzer, OCXAnalyzer


def settings(**changes):
    return Settings(
        _env_file=None, operator_key="test-operator-key-at-least-32-characters",
        analysis_mode="ocx", ocx_base_url="https://ocx.test",
        ocx_api_key="test-only-ocx-key", **changes,
    )


def image():
    stream = io.BytesIO()
    Image.new("RGB", (320, 320), "white").save(stream, "PNG")
    return prepare_image(stream.getvalue(), "image/png")


def test_ocx_uses_only_selected_gateway_and_normalized_photo():
    async def run():
        demo = DemoAnalyzer()
        observation = await demo.observe(image())
        story = await demo.narrate(observation, BoothConfig())
        requests = []

        def handler(request):
            assert str(request.url) == "https://ocx.test/v1/responses"
            assert request.headers["X-OpenCodex-API-Key"] == "test-only-ocx-key"
            assert "Authorization" not in request.headers
            assert "x-api-key" not in request.headers
            body = json.loads(request.content)
            requests.append(body)
            assert body["store"] is False
            assert body["stream"] is True
            assert body["model"] == "gpt-6.1-sol"
            assert body["text"]["format"]["strict"] is True
            result = observation if len(requests) == 1 else story
            return httpx.Response(200, json={"status": "completed", "output": [
                {"type": "reasoning", "summary": []},
                {"type": "message", "content": [{"type": "output_text", "text": result.model_dump_json()}]},
            ]})

        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            analyzer = OCXAnalyzer(settings(), client)
            result = await analyzer.observe(image())
            await analyzer.narrate(result, BoothConfig())
        assert requests[0]["input"][0]["content"][0]["image_url"].startswith("data:image/jpeg;base64,")
        assert all(block["type"] == "input_text" for block in requests[1]["input"][0]["content"])

    asyncio.run(run())


@pytest.mark.parametrize("status,payload,code", [
    (401, {"private": "never-display"}, "provider_configuration"),
    (429, {}, "provider_busy"), (503, {}, "provider_busy"),
    (200, {"status": "incomplete"}, "provider_incomplete"),
    (200, {"status": "completed", "output": []}, "invalid_provider_result"),
    (200, {"status": "completed", "output": None}, "invalid_provider_result"),
])
def test_ocx_failures_never_fall_back_to_demo(status, payload, code):
    async def run():
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(status, json=payload))) as client:
            with pytest.raises(ProviderError) as failure:
                await OCXAnalyzer(settings(), client).observe(image())
            assert failure.value.code == code
            assert "never-display" not in failure.value.message
    asyncio.run(run())


@pytest.mark.parametrize("url", ["", "ftp://ocx.test", "https://user:secret@ocx.test", "https://ocx.test/v1", "https://ocx.test?key=private"])
def test_ocx_rejects_ambiguous_origin(url):
    config = settings()
    config.ocx_base_url = url
    with pytest.raises(ValueError):
        config.validate_runtime()


@pytest.mark.parametrize("terminal", ["completed", "failed", "incomplete", "missing"])
def test_ocx_stream_requires_terminal_completed_event(terminal):
    async def run():
        observation = await DemoAnalyzer().observe(image())
        event = {"type": "response." + terminal, "response": {
            "status": terminal, "output": [{"type": "message", "content": [
                {"type": "output_text", "text": observation.model_dump_json()},
            ]}],
        }}
        body = 'event: response.created\ndata: {"type":"response.created"}\n\n'
        if terminal != "missing":
            body += "data: " + json.dumps(event) + "\n\n"
        body += "data: [DONE]\n\n"
        async with httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(
            200, content=body, headers={"content-type": "text/event-stream"},
        ))) as client:
            if terminal == "completed":
                assert await OCXAnalyzer(settings(), client).observe(image()) == observation
            else:
                with pytest.raises(ProviderError) as failure:
                    await OCXAnalyzer(settings(), client).observe(image())
                assert failure.value.code == "provider_incomplete"
    asyncio.run(run())


def test_ocx_does_not_require_a_direct_anthropic_key():
    config = settings()
    config.validate_runtime()
    assert config.anthropic_api_key is None
    config.ocx_api_key = None
    with pytest.raises(ValueError):
        config.validate_runtime()
