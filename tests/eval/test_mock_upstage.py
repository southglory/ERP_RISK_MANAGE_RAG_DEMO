"""Mock Upstage API 가 OpenAI 호환 응답 형식인지."""

from httpx import ASGITransport, AsyncClient

from mock.upstage_solar_api import app


async def test_mock_models():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.get("/v1/models")
    assert r.status_code == 200
    d = r.json()
    assert d["data"][0]["id"] == "solar-pro"
    assert d["data"][0]["owned_by"] == "upstage"


async def test_mock_chat_completions_openai_shape():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        r = await ac.post(
            "/v1/chat/completions",
            json={
                "model":    "solar-pro",
                "messages": [{"role": "user", "content": "K-IFRS 1115 5단계?"}],
            },
        )
    assert r.status_code == 200
    d = r.json()
    assert "id" in d
    assert d["object"] == "chat.completion"
    msg = d["choices"][0]["message"]
    assert msg["role"] == "assistant"
    assert "K-IFRS 1115 5단계" in msg["content"]
    assert "prompt_tokens" in d["usage"]
    assert "completion_tokens" in d["usage"]
