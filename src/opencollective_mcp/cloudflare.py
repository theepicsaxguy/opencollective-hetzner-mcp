"""Cloudflare client for billing/invoice retrieval.

Uses the Cloudflare API to fetch billing history since there is no
official invoice PDF endpoint. Returns billing events with amounts and dates.

Requires CLOUDFLARE_API_TOKEN environment variable with Billing Read permission.
"""

from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any, Optional

import httpx


class ExchangeRateClient:
    """Client for fetching historical exchange rates from Frankfurter API.

    Frankfurter is a free API for current and historical exchange rates
    published by the European Central Bank. No API key required.
    """

    BASE_URL = "https://api.frankfurter.app"

    def __init__(self) -> None:
        self._client: Optional[httpx.AsyncClient] = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def get_rate(
        self, date: str, from_currency: str = "USD", to_currency: str = "EUR"
    ) -> float:
        """Get exchange rate for a specific date.

        Args:
            date: Date in ISO format (YYYY-MM-DD) or datetime string
            from_currency: Source currency code (default: USD)
            to_currency: Target currency code (default: EUR)

        Returns:
            Exchange rate as float
        """
        # Parse date to extract just the date part
        try:
            if "T" in date:
                date_obj = datetime.fromisoformat(date.replace("Z", "+00:00"))
                date_str = date_obj.strftime("%Y-%m-%d")
            else:
                date_str = date[:10]  # Take first 10 chars (YYYY-MM-DD)
        except (ValueError, IndexError):
            date_str = date[:10] if len(date) >= 10 else date

        client = await self._get_client()
        url = f"{self.BASE_URL}/{date_str}"

        response = await client.get(
            url,
            params={"from": from_currency.upper(), "to": to_currency.upper()},
        )
        response.raise_for_status()

        data = response.json()
        rates = data.get("rates", {})
        rate = rates.get(to_currency.upper())

        if rate is None:
            raise RuntimeError(
                f"No exchange rate found for {to_currency} on {date_str}"
            )

        return float(rate)

    async def convert(
        self,
        amount: float,
        date: str,
        from_currency: str = "USD",
        to_currency: str = "EUR",
    ) -> dict[str, Any]:
        """Convert amount from one currency to another using historical rate.

        Args:
            amount: Amount to convert
            date: Date for historical rate
            from_currency: Source currency
            to_currency: Target currency

        Returns:
            Dict with converted amount, rate, and metadata
        """
        rate = await self.get_rate(date, from_currency, to_currency)
        converted_amount = amount * rate

        # Parse date for return
        try:
            if "T" in date:
                date_obj = datetime.fromisoformat(date.replace("Z", "+00:00"))
                date_str = date_obj.strftime("%Y-%m-%d")
            else:
                date_str = date[:10]
        except (ValueError, IndexError):
            date_str = date[:10] if len(date) >= 10 else date

        return {
            "original_amount": amount,
            "original_currency": from_currency.upper(),
            "converted_amount": round(converted_amount, 2),
            "converted_currency": to_currency.upper(),
            "exchange_rate": rate,
            "rate_date": date_str,
        }


class CloudflareClient:
    """Client for fetching Cloudflare billing data via API.

    This client uses the Cloudflare REST API to fetch billing history.
    Note: The /user/billing/history endpoint is deprecated but still functional.
    It returns billing events rather than actual invoice PDFs.

    Environment variables required:
        CLOUDFLARE_API_TOKEN: API token with Billing Read permission
    """

    BASE_URL = "https://api.cloudflare.com/client/v4"

    def __init__(
        self, api_token: Optional[str] = None, convert_to_eur: bool = True
    ) -> None:
        """Initialize the Cloudflare client.

        Args:
            api_token: Cloudflare API token with Billing Read permission.
                      If not provided, uses CLOUDFLARE_API_TOKEN env var.
            convert_to_eur: Whether to automatically convert USD amounts to EUR
                           using historical exchange rates (default: True)
        """
        self._api_token = api_token or os.environ.get("CLOUDFLARE_API_TOKEN")
        if not self._api_token:
            raise ValueError("CLOUDFLARE_API_TOKEN environment variable must be set")
        self._client: Optional[httpx.AsyncClient] = None
        self._exchange_client: Optional[ExchangeRateClient] = None
        self._convert_to_eur = convert_to_eur

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create the HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(
                headers={
                    "Authorization": f"Bearer {self._api_token}",
                    "Content-Type": "application/json",
                },
                timeout=30.0,
            )
        return self._client

    async def close(self) -> None:
        """Close the HTTP clients."""
        if self._client:
            await self._client.aclose()
            self._client = None
        if self._exchange_client:
            await self._exchange_client.close()
            self._exchange_client = None

    async def _get_exchange_client(self) -> ExchangeRateClient:
        """Get or create the exchange rate client."""
        if self._exchange_client is None:
            self._exchange_client = ExchangeRateClient()
        return self._exchange_client

    async def _request(
        self, method: str, path: str, params: Optional[dict] = None
    ) -> dict[str, Any]:
        """Make an API request."""
        client = await self._get_client()
        url = f"{self.BASE_URL}{path}"

        response = await client.request(method, url, params=params)
        response.raise_for_status()

        data = response.json()
        if not data.get("success"):
            errors = data.get("errors", [])
            error_msg = (
                errors[0].get("message", "Unknown error") if errors else "Unknown error"
            )
            raise RuntimeError(f"Cloudflare API error: {error_msg}")

        return data

    async def list_invoices(
        self,
        page: int = 1,
        per_page: int = 25,
    ) -> dict[str, Any]:
        """List billing history items from Cloudflare.

        Args:
            page: Page number (1-based)
            per_page: Number of items per page (max 50)

        Returns:
            Dict with 'invoices' list and 'pagination' info
        """
        params = {
            "page": page,
            "per_page": min(per_page, 50),  # API max is 50
            "order": "occurred_at",
        }

        data = await self._request("GET", "/user/billing/history", params)
        items = data.get("result", [])

        # Transform to consistent format
        invoices = []
        for item in items:
            # Amount can be float or string like "3.45 usd"
            amount_raw = item.get("amount", 0)
            if isinstance(amount_raw, (int, float)):
                amount = str(amount_raw)
                currency = "USD"  # Default assumption
            else:
                amount, currency = self._parse_amount(str(amount_raw))

            invoice_data = {
                "id": item.get("id"),
                "date": item.get("occurred_at"),
                "amount": amount,
                "currency": currency.upper(),
                "type": item.get("type"),
                "description": item.get("description") or "Cloudflare services",
                "action": item.get("action"),
            }

            # Convert to EUR if enabled and currency is USD
            if self._convert_to_eur and currency.upper() == "USD":
                try:
                    exchange_client = await self._get_exchange_client()
                    conversion = await exchange_client.convert(
                        amount=float(amount),
                        date=item.get("occurred_at", ""),
                        from_currency="USD",
                        to_currency="EUR",
                    )
                    invoice_data["amount_eur"] = str(conversion["converted_amount"])
                    invoice_data["amount_cents_eur"] = int(
                        conversion["converted_amount"] * 100
                    )
                    invoice_data["exchange_rate"] = conversion["exchange_rate"]
                    invoice_data["rate_date"] = conversion["rate_date"]
                except Exception:
                    # If conversion fails, continue without EUR data
                    pass

            invoices.append(invoice_data)

        return {
            "invoices": invoices,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": len(invoices),
            },
        }

    def _parse_amount(self, amount_str: str) -> tuple[str, str]:
        """Parse amount string like '3.45 usd' into (amount, currency).

        Args:
            amount_str: Amount string from API (e.g., "3.45 usd")

        Returns:
            Tuple of (amount_string, currency_code)
        """
        # Handle format like "3.45 usd" or "10.46 USD"
        parts = amount_str.strip().split()
        if len(parts) == 2:
            return parts[0], parts[1]
        # Fallback: try to extract number and assume USD
        match = re.search(r"(\d+\.?\d*)", amount_str)
        if match:
            return match.group(1), "USD"
        return amount_str, "USD"

    async def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        """Get a specific billing item by ID.

        Args:
            invoice_id: The billing item ID

        Returns:
            Dict with invoice details
        """
        # The API doesn't support getting a single item by ID directly,
        # so we fetch all and filter
        data = await self.list_invoices(per_page=100)

        for invoice in data["invoices"]:
            if invoice["id"] == invoice_id:
                return invoice

        raise ValueError(f"Invoice {invoice_id} not found")

    async def get_latest_invoice(self) -> dict[str, Any]:
        """Get the most recent billing item.

        Returns:
            Dict with the latest invoice details
        """
        data = await self.list_invoices(per_page=1, page=1)
        invoices = data.get("invoices", [])

        if not invoices:
            raise ValueError("No invoices found")

        return invoices[0]
