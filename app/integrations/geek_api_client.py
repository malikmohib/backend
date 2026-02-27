import httpx
from app.core.config import settings


class GeekApiClient:
    def __init__(self):
        self.base_url = settings.GEEK_API_BASE_URL
        self.token = settings.GEEK_API_TOKEN
        self.timeout = 15

    async def issue_device(
        self,
        udid: str,
        issue_mode: str,
        pool_type: int,
        warranty: int,
        note: str | None = None,
    ):
        endpoint = (
            "/api/adddevice"
            if issue_mode == "instant"
            else "/api/addyydevice"
        )

        payload = {
            "token": self.token,
            "udid": udid,
            "type": pool_type,
            "warranty": warranty,
            "beizhu": note or "",
        }

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            r = await client.post(f"{self.base_url}{endpoint}", json=payload)

        if r.status_code != 200:
            raise Exception(f"Geek API error: {r.text}")

        return r.json()