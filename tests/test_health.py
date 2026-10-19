import asyncio

from httpx import ASGITransport, AsyncClient

from app.main import app


async def request_health():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        return await client.get("/api/v1/health")


def test_health_status_code() -> None:
    response = asyncio.run(request_health())

    assert response.status_code == 200


def test_health_response_body() -> None:
    response = asyncio.run(request_health())

    assert response.json() == {
        "status": "ok",
        "service": "kcalm-api",
    }
