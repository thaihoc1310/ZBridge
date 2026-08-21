from typing import Any

import httpx

from app.core.config import settings


class GatewayError(Exception):
    def __init__(self, code: str, message: str, status_code: int = 502) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


class ZaloGatewayClient:
    def __init__(self) -> None:
        self.base_url = settings.zalo_gateway_url.rstrip("/")
        self.headers = {"X-Gateway-Secret": settings.zalo_gateway_secret}
        self.timeout = httpx.Timeout(settings.gateway_timeout_seconds, connect=5.0)

    async def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        request_headers = {**self.headers, **kwargs.pop("headers", {})}
        try:
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.request(
                    method, f"{self.base_url}{path}", headers=request_headers, **kwargs
                )
        except (httpx.ConnectError, httpx.TimeoutException) as exc:
            raise GatewayError(
                "ZALO_GATEWAY_UNAVAILABLE",
                "Không thể kết nối tới Zalo Gateway.",
                503,
            ) from exc
        try:
            payload = response.json()
        except ValueError as exc:
            raise GatewayError(
                "ZALO_GATEWAY_UNAVAILABLE", "Gateway trả dữ liệu không hợp lệ."
            ) from exc
        if response.is_error:
            error = payload.get("error", {})
            raise GatewayError(
                str(error.get("code", "ZALO_API_ERROR")),
                str(error.get("message", "Zalo Gateway gặp lỗi.")),
                response.status_code,
            )
        return payload

    async def health(self) -> dict[str, Any]:
        return await self._request("GET", "/health")

    async def get_status(self) -> dict[str, Any]:
        return await self._request("GET", "/bot/status")

    async def connect(self) -> dict[str, Any]:
        return await self._request("POST", "/bot/connect")

    async def get_qr(self) -> dict[str, Any]:
        return await self._request("GET", "/bot/qr")

    async def reconnect(self) -> dict[str, Any]:
        return await self._request("POST", "/bot/reconnect")

    async def disconnect(self) -> dict[str, Any]:
        return await self._request("POST", "/bot/disconnect")

    async def get_groups(self) -> list[dict[str, Any]]:
        payload = await self._request("GET", "/groups")
        return list(payload.get("groups", []))

    async def get_group_members(self, group_id: str) -> list[dict[str, Any]]:
        payload = await self._request("GET", f"/groups/{group_id}/members")
        return list(payload.get("members", []))

    async def get_group_members_batch(
        self, group_ids: list[str]
    ) -> dict[str, list[dict[str, Any]]]:
        """Members of every group in one call, for building the staff roster."""
        response = await self._request(
            "POST", "/groups/members", json={"group_ids": group_ids}
        )
        return response.get("members", {})

    async def send_text(self, group_id: str, content: str) -> dict[str, Any]:
        return await self._request(
            "POST", "/messages/text", json={"group_id": group_id, "content": content}
        )

    async def send_mention(self, group_id: str, targets: list[dict[str, str]]) -> dict[str, Any]:
        return await self._request(
            "POST", "/messages/mention", json={"group_id": group_id, "targets": targets}
        )

    async def send_image(
        self,
        group_id: str,
        image: bytes,
        *,
        width: int,
        height: int,
    ) -> dict[str, Any]:
        return await self._request(
            "POST",
            "/messages/image",
            params={"group_id": group_id, "width": width, "height": height},
            content=image,
            headers={"Content-Type": "image/png"},
        )

    async def send_link(self, group_id: str, link: str) -> dict[str, Any]:
        return await self._request(
            "POST", "/messages/link", json={"group_id": group_id, "link": link}
        )

    async def send_rich_text(
        self, group_id: str, parts: list[dict[str, str]]
    ) -> dict[str, Any]:
        return await self._request(
            "POST", "/messages/rich-text", json={"group_id": group_id, "parts": parts}
        )


zalo_gateway = ZaloGatewayClient()
