"""Browser automation for fetching Hetzner invoices from the web interface.

Since Hetzner does not provide a public API for billing/invoices,
we use Playwright to automate the web interface at accounts.hetzner.com.

Supports automatic 2FA handling via TOTP (time-based one-time password)
if HETZNER_TOTP_SECRET is provided.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Optional

import pyotp
from playwright.async_api import async_playwright, Browser, Page
from playwright_stealth import Stealth  # type: ignore[import-untyped]


@dataclass
class HetznerInvoice:
    """Represents a Hetzner invoice."""

    invoice_id: str
    date: str
    amount: str
    currency: str
    status: str
    pdf_path: Optional[Path] = None
    usage_id: Optional[str] = None


class HetznerBrowserClient:
    """Browser automation client for Hetzner Accounts.

    Requires HETZNER_ACCOUNT_EMAIL and HETZNER_ACCOUNT_PASSWORD env vars.
    Optional: HETZNER_TOTP_SECRET for automatic 2FA handling.

    To get your TOTP secret:
    1. Go to Hetzner Accounts > Security > Two-factor authentication
    2. When setting up 2FA, you'll see a QR code and a "Secret key" or "Setup key"
    3. Copy that secret key and save it as HETZNER_TOTP_SECRET
    """

    BASE_URL = "https://accounts.hetzner.com"
    LOGIN_URL = f"{BASE_URL}/login"
    INVOICES_URL = f"{BASE_URL}/invoice"

    def __init__(
        self,
        email: Optional[str] = None,
        password: Optional[str] = None,
        totp_secret: Optional[str] = None,
        customer_number: Optional[str] = None,
        headless: bool = True,
    ) -> None:
        self.email = email or os.environ.get("HETZNER_ACCOUNT_EMAIL")
        self.password = password or os.environ.get("HETZNER_ACCOUNT_PASSWORD")
        self.totp_secret = totp_secret or os.environ.get("HETZNER_TOTP_SECRET")
        self.customer_number = customer_number or os.environ.get(
            "HETZNER_CUSTOMER_NUMBER"
        )
        self.headless = headless
        self._totp: Optional[pyotp.TOTP] = None
        if self.totp_secret:
            self._totp = pyotp.TOTP(self.totp_secret)
        self._browser: Optional[Browser] = None
        self._page: Optional[Page] = None
        self._playwright = None

    async def __aenter__(self) -> "HetznerBrowserClient":
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self.close()

    async def start(self) -> None:
        """Start the browser with stealth mode to bypass Cloudflare."""
        if not self.email or not self.password:
            raise ValueError(
                "HETZNER_ACCOUNT_EMAIL and HETZNER_ACCOUNT_PASSWORD must be set"
            )

        # Use Stealth context manager for automatic evasion
        self._stealth = Stealth()
        self._playwright_cm = self._stealth.use_async(async_playwright())
        self._playwright = await self._playwright_cm.__aenter__()

        # Launch browser with additional args to avoid detection
        assert self._playwright is not None
        self._browser = await self._playwright.chromium.launch(
            headless=self.headless,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-web-security",
                "--disable-features=IsolateOrigins,site-per-process",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        )

        # Create context with realistic settings
        context = await self._browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            locale="en-US",
            timezone_id="America/New_York",
        )

        self._page = await context.new_page()

    async def close(self) -> None:
        """Close the browser."""
        if self._browser:
            await self._browser.close()
            self._browser = None
            self._page = None
        if self._playwright_cm:
            await self._playwright_cm.__aexit__(None, None, None)
            self._playwright_cm = None
            self._playwright = None

    def _get_totp_code(self) -> str:
        """Generate a TOTP code from the secret."""
        if not self._totp:
            raise RuntimeError("No TOTP secret configured")
        return self._totp.now()

    async def login(self) -> None:
        """Log into Hetzner Accounts, handling 2FA if configured."""
        if not self._page:
            raise RuntimeError("Browser not started. Call start() first.")

        if not self.email or not self.password:
            raise ValueError("Email and password must be set")

        # Type assertion after check
        email: str = self.email
        password: str = self.password

        # Navigate to login page with longer timeout for Cloudflare
        await self._page.goto(
            self.LOGIN_URL, wait_until="domcontentloaded", timeout=30000
        )

        # Wait for page to stabilize
        await self._page.wait_for_timeout(2000)

        # Wait for login form and fill credentials
        # Note: Hetzner uses _username, not email
        await self._page.wait_for_selector('input[name="_username"]', timeout=15000)
        await self._page.fill('input[name="_username"]', email)
        await self._page.fill('input[name="_password"]', password)

        # Submit login form
        await self._page.click('input[type="submit"]')

        # Wait for navigation - handle both direct login and 2FA
        try:
            # Wait for either dashboard or 2FA page
            await self._page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass  # Continue to check URL

        # Check if we're on a 2FA/TOTP page
        current_url = self._page.url
        page_content = await self._page.content()

        is_2fa_page = (
            "totp" in current_url.lower()
            or "2fa" in current_url.lower()
            or "two-factor" in page_content.lower()
            or "2fa" in page_content.lower()
            or "totp" in page_content.lower()
            or 'input[name="totp"]' in page_content
            or 'input[name="code"]' in page_content
            or 'input[name="_auth_code"]' in page_content
        )

        if is_2fa_page:
            if not self._totp:
                raise RuntimeError(
                    "2FA required but no TOTP secret configured. "
                    "Set HETZNER_TOTP_SECRET environment variable."
                )

            # Generate and enter TOTP code
            totp_code = self._get_totp_code()

            # Try to find the TOTP input field
            try:
                # Hetzner uses _auth_code for 2FA
                await self._page.wait_for_selector(
                    'input[name="_auth_code"]',
                    timeout=5000,
                )
                await self._page.fill('input[name="_auth_code"]', totp_code)

                # Submit the 2FA form
                await self._page.click('input[type="submit"]')

                # Wait for redirect to dashboard
                await self._page.wait_for_url(f"{self.BASE_URL}/**", timeout=10000)
            except Exception as e:
                raise RuntimeError(f"Failed to complete 2FA: {e}")
        else:
            # Check if we're on the dashboard
            try:
                await self._page.wait_for_url(f"{self.BASE_URL}/**", timeout=5000)
            except Exception:
                # Check for other error states
                if "login" in self._page.url:
                    raise RuntimeError("Login failed - still on login page")
                # Might already be logged in or on unexpected page
                pass

    async def list_invoices(self, limit: int = 20) -> list[HetznerInvoice]:
        """List invoices from the Hetzner Accounts interface.

        Returns:
            List of HetznerInvoice objects with metadata.
        """
        if not self._page:
            raise RuntimeError("Browser not started. Call start() first.")

        await self._page.goto(self.INVOICES_URL)

        # Wait for invoice list to load (ul.invoice-list)
        await self._page.wait_for_selector("ul.invoice-list", timeout=10000)

        # Extract invoice data from the list
        invoices = []
        items = await self._page.query_selector_all("ul.invoice-list li")

        for item in items[:limit]:
            invoice_id = await item.get_attribute("id")
            if not invoice_id:
                continue

            date_elem = await item.query_selector(".invoice-date")
            amount_elem = await item.query_selector(".invoice-value")
            status_elem = await item.query_selector(".invoice-status")

            date = (await date_elem.inner_text()) if date_elem else ""
            amount_text = (await amount_elem.inner_text()) if amount_elem else ""
            status = (await status_elem.inner_text()) if status_elem else ""

            # Extract usage ID from details link
            usage_id = None
            details_link = await item.query_selector(
                'a.btn-detail[href*="usage.hetzner.com"]'
            )
            if details_link:
                href = await details_link.get_attribute("href")
                if href:
                    # Extract ID from URL like https://usage.hetzner.com/7b65bc9a-6229-4019-99f8-31ef3e0ec8c6
                    usage_id = href.rstrip("/").split("/")[-1]

            # Parse amount and currency
            amount = amount_text.strip()
            currency = "EUR"
            if "€" in amount:
                currency = "EUR"
            elif "$" in amount:
                currency = "USD"

            invoices.append(
                HetznerInvoice(
                    invoice_id=invoice_id,
                    date=date.strip(),
                    amount=amount,
                    currency=currency,
                    status=status.strip(),
                    usage_id=usage_id,
                )
            )

        return invoices

    async def download_invoice_pdf(
        self,
        invoice_id: str,
        download_dir: Optional[Path] = None,
    ) -> Path:
        """Download a specific invoice as PDF.

        Args:
            invoice_id: The invoice ID to download
            download_dir: Directory to save the PDF (defaults to /tmp)

        Returns:
            Path to the downloaded PDF file
        """
        if not self._page:
            raise RuntimeError("Browser not started. Call start() first.")

        download_dir = download_dir or Path("/tmp")
        download_dir.mkdir(parents=True, exist_ok=True)

        # Navigate to invoices page
        await self._page.goto(self.INVOICES_URL)
        await self._page.wait_for_selector("ul.invoice-list", timeout=10000)

        # Find the invoice row and click the PDF link
        # The PDF link is inside the li element with the invoice ID
        pdf_link = await self._page.query_selector(
            f'li[id="{invoice_id}"] a[href*="/pdf"]'
        )

        if not pdf_link:
            raise ValueError(f"Invoice {invoice_id} not found or no PDF available")

        # Set up download handler
        pdf_path = download_dir / f"hetzner_invoice_{invoice_id}.pdf"

        async with self._page.expect_download() as download_info:
            await pdf_link.click()

        download = await download_info.value
        await download.save_as(pdf_path)

        return pdf_path

    async def get_latest_invoice(self) -> HetznerInvoice:
        """Get the most recent invoice.

        Returns:
            HetznerInvoice with the latest invoice data
        """
        invoices = await self.list_invoices(limit=1)
        if not invoices:
            raise ValueError("No invoices found")
        return invoices[0]

    async def get_invoice_details(self, usage_id: str) -> dict[str, Any]:
        """Get detailed invoice information from usage.hetzner.com as CSV.

        Args:
            usage_id: The usage ID from the invoice (e.g., '7b65bc9a-6229-4019-99f8-31ef3e0ec8c6')

        Returns:
            Dict with parsed CSV invoice data
        """
        csv_content = await self.get_invoice_csv(usage_id)

        # Parse CSV
        import csv
        import io

        reader = csv.DictReader(io.StringIO(csv_content))
        rows = list(reader)

        return {
            "usage_id": usage_id,
            "customer_number": self.customer_number,
            "row_count": len(rows),
            "data": rows,
            "csv_raw": csv_content,
        }

    async def get_invoice_csv(self, usage_id: str) -> str:
        """Get invoice data as CSV.

        Args:
            usage_id: The usage ID from the invoice

        Returns:
            CSV content as string
        """
        if not self.customer_number:
            raise ValueError(
                "Customer number required. Set HETZNER_CUSTOMER_NUMBER env var."
            )

        # Fetch CSV directly via HTTP
        import httpx

        csv_url = f"https://usage.hetzner.com/{usage_id}?csv&cn={self.customer_number}"

        # Need to include session cookies from browser
        assert self._page is not None
        cookies = await self._page.context.cookies()
        cookie_header = "; ".join([f"{c['name']}={c['value']}" for c in cookies])

        response = httpx.get(csv_url, headers={"Cookie": cookie_header}, timeout=30)

        return response.text
