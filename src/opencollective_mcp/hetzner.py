"""Hetzner Cloud/Accounts client for invoice retrieval.

Uses browser automation (Playwright) to fetch invoices from accounts.hetzner.com
since Hetzner does not provide a public API for billing/invoices.

Requires HETZNER_ACCOUNT_EMAIL and HETZNER_ACCOUNT_PASSWORD environment variables.
"""

from __future__ import annotations

import io
import re
from typing import Any, Optional

import PyPDF2

from .hetzner_browser import HetznerBrowserClient


class HetznerClient:
    """Client for fetching Hetzner invoices via browser automation.

    This client uses Playwright to automate the Hetzner Accounts web interface
    since there is no public API endpoint for invoices.

    Environment variables required:
        HETZNER_ACCOUNT_EMAIL: Your Hetzner account email
        HETZNER_ACCOUNT_PASSWORD: Your Hetzner account password

    Optional environment variables:
        HETZNER_HEADLESS: Set to 'false' to see the browser (default: 'true')
    """

    def __init__(self, api_token: Optional[str] = None) -> None:
        """Initialize the Hetzner client.

        Note: The api_token parameter is kept for backwards compatibility
        but is not used. Browser automation uses email/password instead.
        """
        self._api_token = api_token  # Kept for compatibility, not used
        self._browser_client: Optional[HetznerBrowserClient] = None

    async def _get_browser_client(self) -> HetznerBrowserClient:
        """Get or create the browser client."""
        if self._browser_client is None:
            import os

            headless = os.environ.get("HETZNER_HEADLESS", "true").lower() != "false"
            self._browser_client = HetznerBrowserClient(headless=headless)
            await self._browser_client.start()
            await self._browser_client.login()
        return self._browser_client

    async def close(self) -> None:
        """Close the browser client."""
        if self._browser_client:
            await self._browser_client.close()
            self._browser_client = None

    async def list_invoices(
        self,
        page: int = 1,
        per_page: int = 25,
    ) -> dict[str, Any]:
        """List invoices from Hetzner Accounts.

        Args:
            page: Page number (1-based, for pagination compatibility)
            per_page: Number of items per page

        Returns:
            Dict with 'invoices' list and 'pagination' info
        """
        client = await self._get_browser_client()
        invoices = await client.list_invoices(limit=per_page)

        # Convert to expected format
        invoice_data = []
        for inv in invoices:
            invoice_data.append(
                {
                    "id": inv.invoice_id,
                    "date": inv.date,
                    "amount": inv.amount,
                    "currency": inv.currency,
                    "status": inv.status,
                }
            )

        return {
            "invoices": invoice_data,
            "pagination": {
                "page": page,
                "per_page": per_page,
                "total": len(invoice_data),
            },
        }

    async def get_invoice(self, invoice_id: str) -> dict[str, Any]:
        """Get a single invoice by ID.

        Args:
            invoice_id: The invoice ID

        Returns:
            Dict with invoice details
        """
        client = await self._get_browser_client()
        invoices = await client.list_invoices(limit=100)

        for inv in invoices:
            if inv.invoice_id == invoice_id:
                return {
                    "id": inv.invoice_id,
                    "date": inv.date,
                    "amount": inv.amount,
                    "currency": inv.currency,
                    "status": inv.status,
                }

        raise ValueError(f"Invoice {invoice_id} not found")

    async def get_invoice_pdf(self, invoice_id: str) -> bytes:
        """Download an invoice as PDF bytes.

        Args:
            invoice_id: The invoice ID

        Returns:
            PDF file contents as bytes
        """
        client = await self._get_browser_client()
        pdf_path = await client.download_invoice_pdf(invoice_id)

        with open(pdf_path, "rb") as f:
            return f.read()

    async def get_invoice_pdf_parsed(self, invoice_id: str) -> dict[str, Any]:
        """Download and parse an invoice PDF.

        Args:
            invoice_id: The invoice ID

        Returns:
            Dict with parsed invoice data
        """
        pdf_bytes = await self.get_invoice_pdf(invoice_id)
        return self._parse_pdf(pdf_bytes, invoice_id)

    def _parse_pdf(self, pdf_bytes: bytes, invoice_id: str) -> dict[str, Any]:
        """Parse PDF content to extract invoice data.

        Args:
            pdf_bytes: PDF file contents
            invoice_id: The invoice ID

        Returns:
            Dict with parsed invoice data
        """
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(pdf_bytes))

        text = ""
        for page in pdf_reader.pages:
            text += page.extract_text() + "\n"

        # Parse common invoice fields
        data = {
            "invoice_id": invoice_id,
            "raw_text": text,
        }

        # Invoice number
        match = re.search(r"Invoice\s*No[:\.]?\s*(\d+)", text, re.IGNORECASE)
        if match:
            data["invoice_number"] = match.group(1)

        # Date
        match = re.search(r"Date[:\.]?\s*([A-Za-z]+\s+\d+,\s+\d{4})", text)
        if match:
            data["date"] = match.group(1)

        # Amount
        match = re.search(r"Total[:\.]?\s*€?\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
        if match:
            data["total"] = match.group(1)

        # Net amount
        match = re.search(r"Net[:\.]?\s*€?\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
        if match:
            data["net_amount"] = match.group(1)

        # VAT
        match = re.search(r"VAT\s*\d+%\s*€?\s*([\d,]+\.\d{2})", text, re.IGNORECASE)
        if match:
            data["vat_amount"] = match.group(1)

        # Customer number
        match = re.search(r"Customer\s*No[:\.]?\s*([A-Z0-9]+)", text, re.IGNORECASE)
        if match:
            data["customer_number"] = match.group(1)

        # Contract/account
        match = re.search(r"Contract[:\.]?\s*(\d+)", text, re.IGNORECASE)
        if match:
            data["contract"] = match.group(1)

        return data

    async def get_latest_invoice(self) -> dict[str, Any]:
        """Get the most recent invoice.

        Returns:
            Dict with the latest invoice details
        """
        client = await self._get_browser_client()
        invoice = await client.get_latest_invoice()

        return {
            "id": invoice.invoice_id,
            "date": invoice.date,
            "amount": invoice.amount,
            "currency": invoice.currency,
            "status": invoice.status,
        }

    async def get_latest_invoice_parsed(self) -> dict[str, Any]:
        """Get the most recent invoice with parsed PDF data.

        Returns:
            Dict with parsed invoice data
        """
        client = await self._get_browser_client()
        invoice = await client.get_latest_invoice()

        # Get parsed PDF
        pdf_parsed = await self.get_invoice_pdf_parsed(invoice.invoice_id)

        return {
            "id": invoice.invoice_id,
            "date": invoice.date,
            "amount": invoice.amount,
            "currency": invoice.currency,
            "status": invoice.status,
            "parsed": pdf_parsed,
        }

    async def get_invoice_details(self, usage_id: str) -> dict[str, Any]:
        """Get detailed invoice data from usage.hetzner.com (CSV).

        Args:
            usage_id: The usage ID from the invoice

        Returns:
            Dict with parsed CSV invoice data
        """
        client = await self._get_browser_client()
        return await client.get_invoice_details(usage_id)
