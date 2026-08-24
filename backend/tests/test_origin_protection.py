import httpx

from app.core.config import settings
from app.main import app


async def test_browser_mutation_rejects_untrusted_origin() -> None:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/auth/logout", headers={"Origin": "https://attacker.example"}
        )

    assert response.status_code == 403
    assert response.json()["error"]["code"] == "UNTRUSTED_ORIGIN"


async def test_browser_mutation_allows_configured_origin_and_machine_client() -> None:
    configured_origin = settings.cors_origins[0]
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        browser = await client.post(
            "/api/auth/logout", headers={"Origin": configured_origin}
        )
        machine = await client.post("/api/auth/logout")

    assert browser.status_code == 204
    assert machine.status_code == 204
