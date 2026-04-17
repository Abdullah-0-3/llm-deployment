from fastapi import Header, HTTPException


class APIKeyAuthenticator:
    def __init__(self, api_key: str | None) -> None:
        self._api_key = api_key

    def __call__(self, x_api_key: str | None = Header(default=None, alias="X-API-Key")) -> str:
        if not self._api_key:
            raise HTTPException(status_code=500, detail="Server API key is not configured")

        if x_api_key != self._api_key:
            raise HTTPException(status_code=401, detail="Invalid or missing API key")

        return x_api_key
