"""GraphQL client for OpenCollective API v2."""

from __future__ import annotations

from typing import Any, Optional

import httpx

API_URL = "https://api.opencollective.com/graphql/v2"
DEFAULT_TIMEOUT = 30.0


class OpenCollectiveClient:
    """Async GraphQL client for the OpenCollective API v2.

    Supports both authenticated (personal token) and unauthenticated requests.
    """

    def __init__(self, personal_token: Optional[str] = None) -> None:
        self.personal_token = personal_token

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self.personal_token:
            headers["Personal-Token"] = self.personal_token
        return headers

    async def execute(
        self,
        query: str,
        variables: Optional[dict[str, Any]] = None,
    ) -> dict[str, Any]:
        """Execute a GraphQL query/mutation and return the result.

        Raises on HTTP errors and surfaces GraphQL errors as exceptions.
        """
        payload: dict[str, Any] = {"query": query}
        if variables:
            payload["variables"] = variables

        async with httpx.AsyncClient(timeout=DEFAULT_TIMEOUT) as client:
            response = await client.post(
                API_URL,
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            result = response.json()

        if "errors" in result:
            msgs = "; ".join(e.get("message", str(e)) for e in result["errors"])
            raise GraphQLError(msgs, result["errors"])

        return result.get("data", {})


class GraphQLError(Exception):
    """Raised when the GraphQL response contains errors."""

    def __init__(self, message: str, errors: list[dict[str, Any]]) -> None:
        super().__init__(message)
        self.errors = errors
