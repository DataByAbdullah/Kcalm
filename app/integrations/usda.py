from dataclasses import dataclass, field
from typing import Any

import httpx


USDA_BASE_URL = "https://api.nal.usda.gov/fdc/v1"


class USDAIntegrationError(Exception):
    def __init__(
        self,
        code: str,
        message: str,
        status_code: int,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(message)


class USDAConfigurationError(USDAIntegrationError):
    def __init__(self) -> None:
        super().__init__(
            code="USDA_API_KEY_MISSING",
            message="USDA_API_KEY is not configured.",
            status_code=503,
        )


class USDATimeoutError(USDAIntegrationError):
    def __init__(self) -> None:
        super().__init__(
            code="USDA_TIMEOUT",
            message="USDA FoodData Central request timed out.",
            status_code=504,
        )


class USDANetworkError(USDAIntegrationError):
    def __init__(self) -> None:
        super().__init__(
            code="USDA_NETWORK_ERROR",
            message="USDA FoodData Central could not be reached.",
            status_code=502,
        )


class USDAAuthenticationError(USDAIntegrationError):
    def __init__(self) -> None:
        super().__init__(
            code="USDA_AUTH_ERROR",
            message="USDA FoodData Central rejected the configured API key.",
            status_code=502,
        )


class USDANotFoundError(USDAIntegrationError):
    def __init__(self, fdc_id: int) -> None:
        super().__init__(
            code="USDA_FOOD_NOT_FOUND",
            message="USDA FoodData Central food was not found.",
            status_code=404,
            details={"fdc_id": fdc_id},
        )


class USDARateLimitError(USDAIntegrationError):
    def __init__(self) -> None:
        super().__init__(
            code="USDA_RATE_LIMITED",
            message="USDA FoodData Central rate limit was reached.",
            status_code=429,
        )


class USDAUpstreamError(USDAIntegrationError):
    def __init__(self, upstream_status_code: int) -> None:
        super().__init__(
            code="USDA_UPSTREAM_ERROR",
            message="USDA FoodData Central returned an upstream error.",
            status_code=502,
            details={"upstream_status_code": upstream_status_code},
        )


class USDAMalformedResponseError(USDAIntegrationError):
    def __init__(self, reason: str) -> None:
        super().__init__(
            code="USDA_MALFORMED_RESPONSE",
            message="USDA FoodData Central returned an unsupported response shape.",
            status_code=502,
            details={"reason": reason},
        )


class USDANoSupportedNutrientsError(USDAIntegrationError):
    def __init__(self, fdc_id: str) -> None:
        super().__init__(
            code="USDA_NO_SUPPORTED_NUTRIENTS",
            message="USDA food did not include supported nutrients for import.",
            status_code=422,
            details={"fdc_id": fdc_id},
        )


@dataclass
class USDAFoodDataCentralClient:
    api_key: str
    base_url: str = USDA_BASE_URL
    timeout_seconds: float = 10.0
    http_client: httpx.Client | None = field(default=None, repr=False)

    def search_foods(
        self,
        query: str,
        page_size: int,
        page_number: int,
    ) -> dict[str, Any]:
        return self._get(
            "/foods/search",
            params={
                "query": query,
                "pageSize": page_size,
                "pageNumber": page_number,
            },
        )

    def get_food(self, fdc_id: int) -> dict[str, Any]:
        return self._get(
            f"/food/{fdc_id}",
            params={"format": "full"},
            not_found_fdc_id=fdc_id,
        )

    def _get(
        self,
        path: str,
        params: dict[str, Any],
        not_found_fdc_id: int | None = None,
    ) -> dict[str, Any]:
        if not self.api_key.strip():
            raise USDAConfigurationError()

        request_params = {**params, "api_key": self.api_key}
        url = f"{self.base_url.rstrip('/')}{path}"

        try:
            if self.http_client is not None:
                response = self.http_client.get(url, params=request_params)
            else:
                with httpx.Client(timeout=self.timeout_seconds) as client:
                    response = client.get(url, params=request_params)
        except httpx.TimeoutException as exc:
            raise USDATimeoutError() from exc
        except httpx.HTTPError as exc:
            raise USDANetworkError() from exc

        if response.status_code in {401, 403}:
            raise USDAAuthenticationError()
        if response.status_code == 404:
            raise USDANotFoundError(not_found_fdc_id or 0)
        if response.status_code == 429:
            raise USDARateLimitError()
        if response.status_code >= 400:
            raise USDAUpstreamError(response.status_code)

        try:
            payload = response.json()
        except ValueError as exc:
            raise USDAMalformedResponseError("response body is not valid JSON") from exc

        if not isinstance(payload, dict):
            raise USDAMalformedResponseError("response JSON is not an object")

        return payload
