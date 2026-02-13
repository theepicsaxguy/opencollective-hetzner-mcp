#!/usr/bin/env python3
"""OpenCollective MCP Server.

Provides tools to interact with the OpenCollective GraphQL API v2 for:
- Account/collective management
- Expense submission and management (INVOICE, RECEIPT, etc.)
- Transaction/ledger queries
- Member/backer queries
- Hetzner Cloud invoice retrieval
"""

from __future__ import annotations

import json
import os
from contextlib import asynccontextmanager
from typing import Any, Optional

import httpx
from mcp.server.fastmcp import FastMCP
from mcp.types import ToolAnnotations
from pydantic import BaseModel, ConfigDict, Field, field_validator

from . import client as oc_client
from . import hetzner as hetzner_client
from . import queries

# ---------------------------------------------------------------------------
# Lifespan: initialize the OpenCollective client once
# ---------------------------------------------------------------------------


@asynccontextmanager
async def app_lifespan(server: FastMCP):
    global _oc_client, _hetzner_client
    oc_token = os.environ.get("OPENCOLLECTIVE_TOKEN")
    _oc_client = oc_client.OpenCollectiveClient(personal_token=oc_token)
    # Hetzner client is lazy - browser starts on first use with email/password
    _hetzner_client = hetzner_client.HetznerClient()
    yield {
        "oc_client": _oc_client,
        "hetzner_client": _hetzner_client,
    }


mcp = FastMCP("opencollective_mcp", lifespan=app_lifespan)

# ---------------------------------------------------------------------------
# Prompts for AI guidance
# ---------------------------------------------------------------------------


@mcp.prompt()
def opencollective_overview() -> str:
    """Overview of OpenCollective MCP tools."""
    return """
# OpenCollective MCP Tools Guide

This MCP provides tools to manage OpenCollective collectives and Hetzner Cloud invoices.

## Quick Reference

### OpenCollective Tools
- `oc_get_account`: Get account details by slug (no auth needed for public data)
- `oc_search_accounts`: Search collectives/organizations
- `oc_list_expenses`: List expenses with filters (status, type, date, tags)
- `oc_create_expense`: Submit new expense (requires auth)
- `oc_process_expense`: Approve/reject/pay expenses
- `oc_edit_account_setting`: Edit account settings
- `oc_set_budget`: Set yearly budget goal (requires token with 'account' scope)
- `oc_execute_graphql`: Run arbitrary GraphQL queries

### Hetzner Tools
- `hetzner_list_invoices`: List all invoices
- `hetzner_get_latest_invoice`: Get most recent invoice
- `hetzner_get_invoice`: Get specific invoice

## Important Notes

1. **Expenses**: When creating expenses, use `payee_slug` matching the collective (for self-hosted) or the vendor slug (e.g., "1040179-hetzner-0267965b")

2. **Dates**: Use ISO 8601 format (YYYY-MM-DD) for dates like `incurred_at`

3. **Amounts**: Use cents (e.g., 6938 for €69.38) or specify amount in EUR directly

4. **Budget Setting**: The `oc_set_budget` tool converts EUR to cents automatically. Just pass amount=800 for €800/year

5. **Token Scopes**: 
   - Read operations: No token needed
   - Create/edit expenses: Token with 'expenses' scope
   - Edit account settings/budget: Token with 'account' scope

## Common Workflows

### Monthly Hetzner Expense Submission
1. `hetzner_get_latest_invoice` - Get the invoice
2. `oc_create_expense` - Submit to OpenCollective with:
   - account_slug: "goingdark"
   - expense_type: "INVOICE"
   - payee_slug: "1040179-hetzner-0267965b" (for Hetzner)
   - amount_cents from invoice
   - reference: invoice ID
   - tags: ["hetzner", "hosting"]

### Check and Update Budget
1. `oc_get_account` - View current stats including yearlyBudget
2. `oc_set_budget` - Update yearly budget (amount in EUR, not cents)
"""


@mcp.prompt()
def expense_creation_guide() -> str:
    """Guide for creating expenses correctly."""
    return """
# Creating OpenCollective Expenses

## Required Parameters
- `account_slug`: The collective to submit to (e.g., "goingdark")
- `description`: What the expense is for
- `payee_slug`: Who receives payment (collective slug or vendor slug)
- `items`: Array with description, amount_cents, currency

## Optional Parameters
- `expense_type`: INVOICE (default), RECEIPT, FUNDING_REQUEST, GRANT
- `tags`: ["hetzner", "hosting"] for categorization
- `reference`: Invoice number from vendor
- `incurred_at`: Date in YYYY-MM-DD format

## Important: Date Format
The `incurred_at` in items MUST be YYYY-MM-DD (e.g., "2026-02-03"), not a full datetime.
The MCP automatically converts this to ISO 8601 format.

## Example: Hetzner Invoice
```
account_slug: "goingdark"
description: "Hetzner Cloud - February 2026"
expense_type: "INVOICE"
payee_slug: "goingdark"  # Or vendor slug like "1040179-hetzner-0267965b"
items: [{
  "description": "Hetzner Cloud - February 2026",
  "amount_cents": 6938,
  "currency": "EUR",
  "incurred_at": "2026-02-03"
}]
reference: "086000667312"
tags: ["hetzner", "hosting"]
```

## Payout Methods
Default is ACCOUNT_BALANCE (pays from collective balance). For external payees, may need PAYPAL or BANK_ACCOUNT.
"""


@mcp.prompt()
def budget_guide() -> str:
    """Guide for setting budgets."""
    return """
# Setting Budget Goals

## oc_set_budget Tool
Simply use the `oc_set_budget` tool:
- `slug`: Account slug (e.g., "goingdark")
- `amount`: Budget in EUR (e.g., 800 for €800/year) - NOT cents
- `title`: Optional title (default: "Yearly Budget")

The tool automatically converts to cents for the API.

## Manual via GraphQL
If needed, use `oc_execute_graphql`:
```graphql
mutation { 
  editAccountSetting(
    account: { slug: "goingdark" }, 
    key: "goals", 
    value: [{ type: "yearlyBudget", title: "Yearly Budget", amount: 80000, currency: "EUR" }]
  ) { id slug name }
}
```
Note: amount is in cents (80000 = €800)

## Requirements
- Token must have 'account' scope
- If you get "Unauthorized" error, the token scope is insufficient
"""


# Module-level clients (initialized by lifespan)
_oc_client: Optional[oc_client.OpenCollectiveClient] = None
_hetzner_client: Optional[hetzner_client.HetznerClient] = None


def _get_client(ctx) -> oc_client.OpenCollectiveClient:
    global _oc_client
    if _oc_client is not None:
        return _oc_client
    if (
        ctx
        and hasattr(ctx, "request_context")
        and hasattr(ctx.request_context, "lifespan_state")
    ):
        return ctx.request_context.lifespan_state["oc_client"]
    # Fallback: create a new client
    oc_token = os.environ.get("OPENCOLLECTIVE_TOKEN")
    _oc_client = oc_client.OpenCollectiveClient(personal_token=oc_token)
    return _oc_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fmt_amount(a: dict | None) -> str:
    if not a:
        return "N/A"
    cents = a.get("valueInCents", 0)
    cur = a.get("currency", "USD")
    return f"{cents / 100:.2f} {cur}"


def _handle_error(e: Exception) -> str:
    if isinstance(e, oc_client.GraphQLError):
        return f"GraphQL error: {e}"
    if isinstance(e, httpx.HTTPStatusError):
        code = e.response.status_code
        if code == 401:
            return "Error: Authentication required. Set OPENCOLLECTIVE_TOKEN environment variable with a personal token."
        if code == 403:
            return "Error: Permission denied. Check your token has the required scopes."
        if code == 429:
            return "Error: Rate limit exceeded. Wait before retrying."
        return f"Error: HTTP {code}"
    if isinstance(e, httpx.TimeoutException):
        return "Error: Request timed out."
    return f"Error: {type(e).__name__}: {e}"


# ---------------------------------------------------------------------------
# Input models
# ---------------------------------------------------------------------------


class AccountRefInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    slug: Optional[str] = Field(
        default=None, description="Account slug (e.g. 'goingdark')"
    )
    id: Optional[str] = Field(default=None, description="Account ID")


class GetAccountInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    slug: str = Field(
        ..., description="The collective/account slug (e.g. 'goingdark')", min_length=1
    )


class SearchAccountsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    search_term: Optional[str] = Field(default=None, description="Search query string")
    account_type: Optional[str] = Field(
        default=None,
        description="Filter by type: COLLECTIVE, ORGANIZATION, INDIVIDUAL, FUND, PROJECT, EVENT",
    )
    limit: int = Field(default=20, ge=1, le=100, description="Max results")
    offset: int = Field(default=0, ge=0, description="Pagination offset")


class GetMembersInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    slug: str = Field(..., description="Account slug", min_length=1)
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class ListExpensesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    account_slug: Optional[str] = Field(
        default=None, description="Collective slug to list expenses for"
    )
    from_account_slug: Optional[str] = Field(
        default=None, description="Filter by payee slug"
    )
    status: Optional[list[str]] = Field(
        default=None,
        description="Filter by status(es): DRAFT, PENDING, APPROVED, REJECTED, PAID, PROCESSING, ERROR, SCHEDULED_FOR_PAYMENT, CANCELED, INCOMPLETE, UNVERIFIED, SPAM",
    )
    expense_type: Optional[str] = Field(
        default=None,
        description="Filter by type: INVOICE, RECEIPT, FUNDING_REQUEST, GRANT, UNCLASSIFIED, CHARGE",
    )
    tag: Optional[list[str]] = Field(default=None, description="Filter by tag(s)")
    date_from: Optional[str] = Field(default=None, description="Start date (ISO 8601)")
    date_to: Optional[str] = Field(default=None, description="End date (ISO 8601)")
    search_term: Optional[str] = Field(
        default=None, description="Search in description"
    )
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class GetExpenseInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    id: Optional[str] = Field(default=None, description="Expense ID (string)")
    legacy_id: Optional[int] = Field(
        default=None, description="Expense legacy ID (integer)"
    )


class ExpenseItemInput(BaseModel):
    description: str = Field(..., description="Item description", min_length=1)
    amount_cents: int = Field(
        ..., description="Amount in cents (e.g. 5000 for $50.00)", gt=0
    )
    currency: str = Field(
        default="USD", description="Currency code (e.g. 'USD', 'EUR', 'SEK')"
    )
    url: Optional[str] = Field(default=None, description="URL to receipt/invoice image")
    incurred_at: Optional[str] = Field(
        default=None, description="Date the expense was incurred (ISO 8601)"
    )


class CreateExpenseInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    account_slug: str = Field(
        ...,
        description="Collective slug to submit expense to (e.g. 'goingdark')",
        min_length=1,
    )
    description: str = Field(..., description="Expense description/title", min_length=1)
    expense_type: str = Field(
        default="INVOICE",
        description="Expense type: INVOICE, RECEIPT, FUNDING_REQUEST, GRANT, UNCLASSIFIED",
    )
    payee_slug: str = Field(
        ..., description="Slug of account receiving the payment", min_length=1
    )
    items: list[ExpenseItemInput] = Field(
        ..., description="Line items for the expense", min_length=1
    )
    currency: Optional[str] = Field(default=None, description="Currency code override")
    long_description: Optional[str] = Field(
        default=None, description="Detailed description"
    )
    tags: Optional[list[str]] = Field(
        default=None, description="Tags for categorization"
    )
    private_message: Optional[str] = Field(
        default=None, description="Private note to admins"
    )
    invoice_info: Optional[str] = Field(
        default=None, description="Invoice information (address, tax ID, etc.)"
    )
    payout_method_id: Optional[str] = Field(
        default=None, description="ID of existing payout method"
    )
    payout_method_type: Optional[str] = Field(
        default=None,
        description="Payout type if creating new: OTHER, PAYPAL, BANK_ACCOUNT, ACCOUNT_BALANCE",
    )
    payout_method_data: Optional[dict] = Field(
        default=None, description="Payout method data (e.g. PayPal email, bank details)"
    )
    reference: Optional[str] = Field(
        default=None, description="External reference number"
    )
    recurring_interval: Optional[str] = Field(
        default=None, description="Recurring interval: MONTH, QUARTER, YEAR"
    )

    @field_validator("expense_type")
    @classmethod
    def validate_expense_type(cls, v: str) -> str:
        valid = {
            "INVOICE",
            "RECEIPT",
            "FUNDING_REQUEST",
            "GRANT",
            "UNCLASSIFIED",
            "CHARGE",
        }
        v = v.upper()
        if v not in valid:
            raise ValueError(
                f"Invalid expense type '{v}'. Must be one of: {', '.join(sorted(valid))}"
            )
        return v


class EditExpenseInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    id: str = Field(..., description="Expense ID to edit", min_length=1)
    description: Optional[str] = Field(default=None, description="New description")
    long_description: Optional[str] = Field(
        default=None, description="New detailed description"
    )
    tags: Optional[list[str]] = Field(default=None, description="New tags")
    private_message: Optional[str] = Field(
        default=None, description="New private message"
    )
    invoice_info: Optional[str] = Field(default=None, description="New invoice info")
    reference: Optional[str] = Field(default=None, description="New reference number")
    expense_type: Optional[str] = Field(
        default=None, description="New type: INVOICE, RECEIPT, etc."
    )


class DeleteExpenseInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    id: Optional[str] = Field(default=None, description="Expense ID")
    legacy_id: Optional[int] = Field(default=None, description="Expense legacy ID")


class ProcessExpenseInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    id: Optional[str] = Field(default=None, description="Expense ID")
    legacy_id: Optional[int] = Field(default=None, description="Expense legacy ID")
    action: str = Field(
        ...,
        description="Action: APPROVE, UNAPPROVE, REJECT, PAY, MARK_AS_UNPAID, SCHEDULE_FOR_PAYMENT, UNSCHEDULE_PAYMENT, MARK_AS_SPAM, MARK_AS_INCOMPLETE, HOLD, RELEASE",
    )
    message: Optional[str] = Field(default=None, description="Optional message/comment")

    @field_validator("action")
    @classmethod
    def validate_action(cls, v: str) -> str:
        valid = {
            "APPROVE",
            "UNAPPROVE",
            "REQUEST_RE_APPROVAL",
            "REJECT",
            "MARK_AS_UNPAID",
            "SCHEDULE_FOR_PAYMENT",
            "UNSCHEDULE_PAYMENT",
            "PAY",
            "MARK_AS_SPAM",
            "MARK_AS_INCOMPLETE",
            "HOLD",
            "RELEASE",
        }
        v = v.upper()
        if v not in valid:
            raise ValueError(
                f"Invalid action '{v}'. Must be one of: {', '.join(sorted(valid))}"
            )
        return v


class ListTransactionsInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    account_slug: Optional[str] = Field(
        default=None, description="Account slug to list transactions for"
    )
    transaction_type: Optional[str] = Field(default=None, description="CREDIT or DEBIT")
    date_from: Optional[str] = Field(default=None, description="Start date (ISO 8601)")
    date_to: Optional[str] = Field(default=None, description="End date (ISO 8601)")
    search_term: Optional[str] = Field(default=None, description="Search term")
    kind: Optional[list[str]] = Field(
        default=None,
        description="Filter by kind: CONTRIBUTION, EXPENSE, ADDED_FUNDS, HOST_FEE, PAYMENT_PROCESSOR_FEE, etc.",
    )
    limit: int = Field(default=20, ge=1, le=100)
    offset: int = Field(default=0, ge=0)


class EditAccountInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    id: str = Field(
        ...,
        description="Account ID to edit (required, get it from oc_get_account first)",
        min_length=1,
    )
    name: Optional[str] = Field(default=None, description="New display name")
    legal_name: Optional[str] = Field(default=None, description="New legal name")
    description: Optional[str] = Field(
        default=None, description="New short description"
    )
    long_description: Optional[str] = Field(
        default=None, description="New long description (markdown)"
    )
    tags: Optional[list[str]] = Field(default=None, description="New tags")
    currency: Optional[str] = Field(default=None, description="New currency code")


class EditAccountSettingInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    slug: str = Field(
        ..., description="Account slug to edit settings for", min_length=1
    )
    key: str = Field(
        ...,
        description="Setting key (e.g. 'expensesMonthlyLimit', 'VIRTUAL_CARDS_MAX_MONTHLY_AMOUNT')",
        min_length=1,
    )
    value: Any = Field(..., description="Value to set (string, number, or boolean)")


class SetBudgetInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    slug: str = Field(..., description="Account slug (e.g. 'goingdark')", min_length=1)
    amount: int = Field(
        ..., description="Budget amount in EUR (e.g. 800 for €800/year)", ge=1
    )
    title: str = Field(
        default="Yearly Budget", description="Display title for the goal"
    )


class ExecuteGraphQLInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    query: str = Field(
        ..., description="Raw GraphQL query or mutation string", min_length=1
    )
    variables: Optional[dict[str, Any]] = Field(
        default=None, description="Variables for the query"
    )


# ---------------------------------------------------------------------------
# Tools: Accounts
# ---------------------------------------------------------------------------


@mcp.tool(
    name="oc_get_account",
    annotations={
        "title": "Get OpenCollective Account",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def oc_get_account(params: GetAccountInput, ctx=None) -> str:
    """Get detailed information about an OpenCollective account/collective by slug.

    Returns account profile, stats (balance, budget, total received/spent),
    social links, and metadata. Works without authentication for public data.
    """
    try:
        cl = _get_client(ctx)
        data = await cl.execute(queries.GET_ACCOUNT, {"slug": params.slug})
        account = data.get("account")
        if not account:
            return f"No account found with slug '{params.slug}'"
        return json.dumps(account, indent=2)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="oc_search_accounts",
    annotations={
        "title": "Search OpenCollective Accounts",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def oc_search_accounts(params: SearchAccountsInput, ctx=None) -> str:
    """Search for OpenCollective accounts/collectives.

    Supports filtering by search term and account type
    (COLLECTIVE, ORGANIZATION, INDIVIDUAL, FUND, PROJECT, EVENT).
    """
    try:
        cl = _get_client(ctx)
        variables: dict[str, Any] = {
            "limit": params.limit,
            "offset": params.offset,
        }
        if params.search_term:
            variables["searchTerm"] = params.search_term
        if params.account_type:
            variables["type"] = [params.account_type.upper()]
        data = await cl.execute(queries.SEARCH_ACCOUNTS, variables)
        return json.dumps(data.get("accounts", {}), indent=2)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="oc_get_logged_in_account",
    annotations={
        "title": "Get Current Authenticated Account",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": False,
    },
)
async def oc_get_logged_in_account(ctx=None) -> str:
    """Get information about the currently authenticated account.

    Requires OPENCOLLECTIVE_TOKEN to be set.
    """
    try:
        cl = _get_client(ctx)
        if not cl.personal_token:
            return "Error: No authentication token set. Set OPENCOLLECTIVE_TOKEN environment variable."
        data = await cl.execute(queries.GET_LOGGED_IN_ACCOUNT)
        return json.dumps(data.get("loggedInAccount", {}), indent=2)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="oc_edit_account",
    annotations={
        "title": "Edit OpenCollective Account",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def oc_edit_account(params: EditAccountInput, ctx=None) -> str:
    """Edit an OpenCollective account/collective profile.

    Requires authentication. Use oc_get_account first to obtain the account ID.
    Only provided fields will be updated.
    """
    try:
        cl = _get_client(ctx)
        account_input: dict[str, Any] = {"id": params.id}
        if params.name is not None:
            account_input["name"] = params.name
        if params.legal_name is not None:
            account_input["legalName"] = params.legal_name
        if params.description is not None:
            account_input["description"] = params.description
        if params.long_description is not None:
            account_input["longDescription"] = params.long_description
        if params.tags is not None:
            account_input["tags"] = params.tags
        if params.currency is not None:
            account_input["currency"] = params.currency

        data = await cl.execute(queries.EDIT_ACCOUNT, {"account": account_input})
        return json.dumps(data.get("editAccount", {}), indent=2)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="oc_edit_account_setting",
    annotations={
        "title": "Edit Account Setting",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def oc_edit_account_setting(params: EditAccountSettingInput, ctx=None) -> str:
    """Edit an account setting like monthly spending limits.

    Requires authentication with account scope.
    Common keys:
    - 'expensesMonthlyLimit': Monthly expense limit in EUR
    - 'VIRTUAL_CARDS_MAX_MONTHLY_AMOUNT': Max monthly virtual card spending
    - 'VIRTUAL_CARDS_MAX_DAILY_AMOUNT': Max daily virtual card spending
    """
    try:
        cl = _get_client(ctx)
        variables = {
            "account": {"slug": params.slug},
            "key": params.key,
            "value": params.value,
        }
        data = await cl.execute(queries.EDIT_ACCOUNT_SETTING, variables)
        return json.dumps(data.get("editAccountSetting", {}), indent=2)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="oc_set_budget",
    annotations={
        "title": "Set Yearly Budget Goal",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def oc_set_budget(params: SetBudgetInput, ctx=None) -> str:
    """Set the yearly budget goal for a collective.

    Example: Set 800 EUR yearly budget for goingdark collective.
    Requires token with 'account' scope.
    """
    try:
        cl = _get_client(ctx)
        variables = {
            "account": {"slug": params.slug},
            "key": "goals",
            "value": [
                {
                    "type": "yearlyBudget",
                    "title": params.title,
                    "amount": params.amount * 100,  # Convert to cents
                    "currency": "EUR",
                }
            ],
        }
        data = await cl.execute(queries.EDIT_ACCOUNT_SETTING, variables)
        return json.dumps(data.get("editAccountSetting", {}), indent=2)
    except Exception as e:
        return _handle_error(e)


# ---------------------------------------------------------------------------
# Tools: Members
# ---------------------------------------------------------------------------


@mcp.tool(
    name="oc_get_members",
    annotations={
        "title": "Get Account Members/Backers",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def oc_get_members(params: GetMembersInput, ctx=None) -> str:
    """List members and backers of an OpenCollective account.

    Returns member roles (ADMIN, MEMBER, BACKER, etc.), donation totals,
    and linked account info.
    """
    try:
        cl = _get_client(ctx)
        data = await cl.execute(
            queries.GET_MEMBERS,
            {
                "slug": params.slug,
                "limit": params.limit,
                "offset": params.offset,
            },
        )
        members = data.get("account", {}).get("members", {})
        return json.dumps(members, indent=2)
    except Exception as e:
        return _handle_error(e)


# ---------------------------------------------------------------------------
# Tools: Expenses
# ---------------------------------------------------------------------------


@mcp.tool(
    name="oc_list_expenses",
    annotations={
        "title": "List Expenses",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def oc_list_expenses(params: ListExpensesInput, ctx=None) -> str:
    """List expenses for an OpenCollective account with filtering.

    Supports filtering by status, type, tags, date range, and search term.
    Use account_slug to filter by collective, from_account_slug to filter by payee.
    """
    try:
        cl = _get_client(ctx)
        variables: dict[str, Any] = {
            "limit": params.limit,
            "offset": params.offset,
        }
        if params.account_slug:
            variables["account"] = {"slug": params.account_slug}
        if params.from_account_slug:
            variables["fromAccount"] = {"slug": params.from_account_slug}
        if params.status:
            variables["status"] = [s.upper() for s in params.status]
        if params.expense_type:
            variables["type"] = params.expense_type.upper()
        if params.tag:
            variables["tag"] = params.tag
        if params.date_from:
            variables["dateFrom"] = params.date_from
        if params.date_to:
            variables["dateTo"] = params.date_to
        if params.search_term:
            variables["searchTerm"] = params.search_term

        data = await cl.execute(queries.LIST_EXPENSES, variables)
        return json.dumps(data.get("expenses", {}), indent=2)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="oc_get_expense",
    annotations={
        "title": "Get Expense Details",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def oc_get_expense(params: GetExpenseInput, ctx=None) -> str:
    """Get detailed information about a specific expense by ID or legacy ID."""
    try:
        cl = _get_client(ctx)
        variables: dict[str, Any] = {}
        if params.id:
            variables["id"] = params.id
        if params.legacy_id:
            variables["legacyId"] = params.legacy_id
        if not variables:
            return "Error: Provide either 'id' or 'legacy_id'"
        data = await cl.execute(queries.GET_EXPENSE, variables)
        return json.dumps(data.get("expense", {}), indent=2)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="oc_create_expense",
    annotations={
        "title": "Create/Submit Expense",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def oc_create_expense(params: CreateExpenseInput, ctx=None) -> str:
    """Submit a new expense to an OpenCollective collective.

    Supports INVOICE, RECEIPT, FUNDING_REQUEST, GRANT, and UNCLASSIFIED types.
    Each expense requires at least one line item with description and amount.

    The payee is the account that will receive the payment. The account is the
    collective the expense is submitted to. Requires authentication.

    For bookkeeping expenses (e.g. when collective has negative balance),
    submit as INVOICE type.
    """
    try:
        cl = _get_client(ctx)

        items = []
        for item in params.items:
            item_data: dict[str, Any] = {
                "description": item.description,
                "amountV2": {
                    "valueInCents": item.amount_cents,
                    "currency": item.currency,
                },
            }
            if item.url:
                item_data["url"] = item.url
            if item.incurred_at:
                # Ensure ISO 8601 datetime format
                incurred = item.incurred_at
                if len(incurred) == 10:  # YYYY-MM-DD format
                    incurred = f"{incurred}T00:00:00Z"
                item_data["incurredAt"] = incurred
            items.append(item_data)

        expense_input: dict[str, Any] = {
            "description": params.description,
            "type": params.expense_type,
            "payee": {"slug": params.payee_slug},
            "items": items,
        }

        # Payout method
        payout: dict[str, Any] = {}
        if params.payout_method_id:
            payout["id"] = params.payout_method_id
        if params.payout_method_type:
            payout["type"] = params.payout_method_type
        if params.payout_method_data:
            payout["data"] = params.payout_method_data
        if not payout:
            # Default to ACCOUNT_BALANCE for collectives
            payout = {"type": "ACCOUNT_BALANCE"}
        expense_input["payoutMethod"] = payout

        if params.currency:
            expense_input["currency"] = params.currency
        if params.long_description:
            expense_input["longDescription"] = params.long_description
        if params.tags:
            expense_input["tags"] = params.tags
        if params.private_message:
            expense_input["privateMessage"] = params.private_message
        if params.invoice_info:
            expense_input["invoiceInfo"] = params.invoice_info
        if params.reference:
            expense_input["reference"] = params.reference

        variables: dict[str, Any] = {
            "expense": expense_input,
            "account": {"slug": params.account_slug},
        }

        if params.recurring_interval:
            variables["recurring"] = {"interval": params.recurring_interval.upper()}

        data = await cl.execute(queries.CREATE_EXPENSE, variables)
        return json.dumps(data.get("createExpense", {}), indent=2)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="oc_edit_expense",
    annotations={
        "title": "Edit Expense",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def oc_edit_expense(params: EditExpenseInput, ctx=None) -> str:
    """Edit an existing expense. Only provided fields will be updated.

    Requires authentication and appropriate permissions.
    """
    try:
        cl = _get_client(ctx)
        expense_input: dict[str, Any] = {"id": params.id}
        if params.description is not None:
            expense_input["description"] = params.description
        if params.long_description is not None:
            expense_input["longDescription"] = params.long_description
        if params.tags is not None:
            expense_input["tags"] = params.tags
        if params.private_message is not None:
            expense_input["privateMessage"] = params.private_message
        if params.invoice_info is not None:
            expense_input["invoiceInfo"] = params.invoice_info
        if params.reference is not None:
            expense_input["reference"] = params.reference
        if params.expense_type is not None:
            expense_input["type"] = params.expense_type.upper()

        data = await cl.execute(queries.EDIT_EXPENSE, {"expense": expense_input})
        return json.dumps(data.get("editExpense", {}), indent=2)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="oc_delete_expense",
    annotations={
        "title": "Delete Expense",
        "readOnlyHint": False,
        "destructiveHint": True,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def oc_delete_expense(params: DeleteExpenseInput, ctx=None) -> str:
    """Delete an expense. Requires authentication and appropriate permissions."""
    try:
        cl = _get_client(ctx)
        variables: dict[str, Any] = {}
        if params.id:
            variables["id"] = params.id
        if params.legacy_id:
            variables["legacyId"] = params.legacy_id
        if not variables:
            return "Error: Provide either 'id' or 'legacy_id'"
        data = await cl.execute(queries.DELETE_EXPENSE, variables)
        return json.dumps(data.get("deleteExpense", {}), indent=2)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="oc_process_expense",
    annotations={
        "title": "Process Expense (Approve/Reject/Pay)",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def oc_process_expense(params: ProcessExpenseInput, ctx=None) -> str:
    """Process an expense: approve, reject, pay, hold, release, etc.

    Available actions: APPROVE, UNAPPROVE, REQUEST_RE_APPROVAL, REJECT,
    MARK_AS_UNPAID, SCHEDULE_FOR_PAYMENT, UNSCHEDULE_PAYMENT, PAY,
    MARK_AS_SPAM, MARK_AS_INCOMPLETE, HOLD, RELEASE.

    Requires authentication and admin/host permissions.
    """
    try:
        cl = _get_client(ctx)
        variables: dict[str, Any] = {"action": params.action}
        if params.id:
            variables["id"] = params.id
        if params.legacy_id:
            variables["legacyId"] = params.legacy_id
        if params.message:
            variables["message"] = params.message
        if not params.id and not params.legacy_id:
            return "Error: Provide either 'id' or 'legacy_id'"
        data = await cl.execute(queries.PROCESS_EXPENSE, variables)
        return json.dumps(data.get("processExpense", {}), indent=2)
    except Exception as e:
        return _handle_error(e)


# ---------------------------------------------------------------------------
# Tools: Transactions
# ---------------------------------------------------------------------------


@mcp.tool(
    name="oc_list_transactions",
    annotations={
        "title": "List Transactions (Ledger)",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def oc_list_transactions(params: ListTransactionsInput, ctx=None) -> str:
    """List transactions for an OpenCollective account (the ledger).

    Shows credits and debits with amounts, descriptions, linked expenses/orders.
    Supports filtering by type (CREDIT/DEBIT), date range, kind, and search term.
    """
    try:
        cl = _get_client(ctx)
        variables: dict[str, Any] = {
            "limit": params.limit,
            "offset": params.offset,
        }
        if params.account_slug:
            variables["account"] = [{"slug": params.account_slug}]
        if params.transaction_type:
            variables["type"] = params.transaction_type.upper()
        if params.date_from:
            variables["dateFrom"] = params.date_from
        if params.date_to:
            variables["dateTo"] = params.date_to
        if params.search_term:
            variables["searchTerm"] = params.search_term
        if params.kind:
            variables["kind"] = [k.upper() for k in params.kind]

        data = await cl.execute(queries.LIST_TRANSACTIONS, variables)
        return json.dumps(data.get("transactions", {}), indent=2)
    except Exception as e:
        return _handle_error(e)


# ---------------------------------------------------------------------------
# Tools: Raw GraphQL (escape hatch)
# ---------------------------------------------------------------------------


@mcp.tool(
    name="oc_execute_graphql",
    annotations={
        "title": "Execute Raw GraphQL",
        "readOnlyHint": False,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def oc_execute_graphql(params: ExecuteGraphQLInput, ctx=None) -> str:
    """Execute a raw GraphQL query or mutation against the OpenCollective API v2.

    Use this as an escape hatch for operations not covered by other tools.
    The API endpoint is https://api.opencollective.com/graphql/v2.
    Authentication is applied automatically if OPENCOLLECTIVE_TOKEN is set.
    """
    try:
        cl = _get_client(ctx)
        data = await cl.execute(params.query, params.variables)
        return json.dumps(data, indent=2)
    except Exception as e:
        return _handle_error(e)


# ---------------------------------------------------------------------------
# Hetzner helpers and input models
# ---------------------------------------------------------------------------


def _get_hetzner_client(ctx) -> hetzner_client.HetznerClient:
    global _hetzner_client
    if _hetzner_client is not None:
        return _hetzner_client
    if (
        ctx
        and hasattr(ctx, "request_context")
        and hasattr(ctx.request_context, "lifespan_state")
    ):
        return ctx.request_context.lifespan_state["hetzner_client"]
    # Fallback: create a new client
    _hetzner_client = hetzner_client.HetznerClient()
    return _hetzner_client


class HetznerListInvoicesInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    page: int = Field(default=1, ge=1, description="Page number")
    per_page: int = Field(
        default=25, ge=1, le=50, description="Items per page (max 50)"
    )


class HetznerGetInvoiceInput(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    invoice_id: str = Field(..., description="Invoice ID", min_length=1)


# ---------------------------------------------------------------------------
# Tools: Hetzner Invoices
# ---------------------------------------------------------------------------


@mcp.tool(
    name="hetzner_list_invoices",
    annotations={
        "title": "List Hetzner Cloud Invoices",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def hetzner_list_invoices(params: HetznerListInvoicesInput, ctx=None) -> str:
    """List invoices from Hetzner Cloud.

    Returns paginated invoice data. Requires HETZNER_ACCOUNT_EMAIL and HETZNER_ACCOUNT_PASSWORD to be set.
    Uses browser automation to fetch invoices from accounts.hetzner.com.
    """
    try:
        email = os.environ.get("HETZNER_ACCOUNT_EMAIL")
        password = os.environ.get("HETZNER_ACCOUNT_PASSWORD")
        if not email or not password:
            return "Error: HETZNER_ACCOUNT_EMAIL and HETZNER_ACCOUNT_PASSWORD environment variables must be set."
        cl = _get_hetzner_client(ctx)
        data = await cl.list_invoices(page=params.page, per_page=params.per_page)
        return json.dumps(data, indent=2)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="hetzner_get_invoice",
    annotations={
        "title": "Get Hetzner Cloud Invoice",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def hetzner_get_invoice(params: HetznerGetInvoiceInput, ctx=None) -> str:
    """Get details of a specific Hetzner Cloud invoice by ID.

    Requires HETZNER_ACCOUNT_EMAIL and HETZNER_ACCOUNT_PASSWORD to be set.
    """
    try:
        email = os.environ.get("HETZNER_ACCOUNT_EMAIL")
        password = os.environ.get("HETZNER_ACCOUNT_PASSWORD")
        if not email or not password:
            return "Error: HETZNER_ACCOUNT_EMAIL and HETZNER_ACCOUNT_PASSWORD environment variables must be set."
        cl = _get_hetzner_client(ctx)
        data = await cl.get_invoice(params.invoice_id)
        return json.dumps(data, indent=2)
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="hetzner_get_latest_invoice",
    annotations={
        "title": "Get Latest Hetzner Cloud Invoice",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": False,
        "openWorldHint": True,
    },
)
async def hetzner_get_latest_invoice(ctx=None) -> str:
    """Get the most recent Hetzner Cloud invoice.

    Fetches the first page of invoices and returns the latest one.
    Requires HETZNER_ACCOUNT_EMAIL and HETZNER_ACCOUNT_PASSWORD to be set.

    Useful for automated monthly bookkeeping: fetch the latest Hetzner invoice
    and then use oc_create_expense to submit it to OpenCollective.
    """
    try:
        email = os.environ.get("HETZNER_ACCOUNT_EMAIL")
        password = os.environ.get("HETZNER_ACCOUNT_PASSWORD")
        if not email or not password:
            return "Error: HETZNER_ACCOUNT_EMAIL and HETZNER_ACCOUNT_PASSWORD environment variables must be set."
        cl = _get_hetzner_client(ctx)
        data = await cl.get_latest_invoice()
        return json.dumps(data, indent=2)
    except Exception as e:
        return _handle_error(e)


class HetznerGetInvoicePdfInput(BaseModel):
    invoice_id: str = Field(description="The invoice ID to download")


@mcp.tool(
    name="hetzner_get_invoice_pdf",
    annotations={
        "title": "Download Hetzner Invoice PDF",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def hetzner_get_invoice_pdf(params: HetznerGetInvoicePdfInput, ctx=None) -> str:
    """Download a Hetzner invoice as PDF.

    Returns the PDF content as base64-encoded string.
    Requires HETZNER_ACCOUNT_EMAIL and HETZNER_ACCOUNT_PASSWORD to be set.
    """
    try:
        import base64

        email = os.environ.get("HETZNER_ACCOUNT_EMAIL")
        password = os.environ.get("HETZNER_ACCOUNT_PASSWORD")
        if not email or not password:
            return "Error: HETZNER_ACCOUNT_EMAIL and HETZNER_ACCOUNT_PASSWORD environment variables must be set."
        cl = _get_hetzner_client(ctx)
        pdf_bytes = await cl.get_invoice_pdf(params.invoice_id)
        b64 = base64.b64encode(pdf_bytes).decode("utf-8")
        return json.dumps(
            {
                "invoice_id": params.invoice_id,
                "content": b64,
                "content_type": "application/pdf",
            }
        )
    except Exception as e:
        return _handle_error(e)


@mcp.tool(
    name="hetzner_parse_invoice_pdf",
    annotations={
        "title": "Parse Hetzner Invoice PDF to JSON",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def hetzner_parse_invoice_pdf(params: HetznerGetInvoicePdfInput, ctx=None) -> str:
    """Download and parse a Hetzner invoice PDF to JSON.

    Extracts invoice data like invoice number, date, amount, net, VAT, etc.
    Requires HETZNER_ACCOUNT_EMAIL and HETZNER_ACCOUNT_PASSWORD to be set.
    """
    try:
        email = os.environ.get("HETZNER_ACCOUNT_EMAIL")
        password = os.environ.get("HETZNER_ACCOUNT_PASSWORD")
        if not email or not password:
            return "Error: HETZNER_ACCOUNT_EMAIL and HETZNER_ACCOUNT_PASSWORD environment variables must be set."
        cl = _get_hetzner_client(ctx)
        data = await cl.get_invoice_pdf_parsed(params.invoice_id)
        return json.dumps(data, indent=2)
    except Exception as e:
        return _handle_error(e)


class HetznerGetInvoiceDetailsInput(BaseModel):
    usage_id: str = Field(
        description="The usage ID from the invoice (e.g., '7b65bc9a-6229-4019-99f8-31ef3e0ec8c6')"
    )


@mcp.tool(
    name="hetzner_get_invoice_details",
    annotations={
        "title": "Get Hetzner Invoice Details",
        "readOnlyHint": True,
        "destructiveHint": False,
        "idempotentHint": True,
        "openWorldHint": True,
    },
)
async def hetzner_get_invoice_details(
    params: HetznerGetInvoiceDetailsInput, ctx=None
) -> str:
    """Get detailed invoice information from Hetzner usage portal.

    Fetches invoice line items as CSV from usage.hetzner.com.
    Requires HETZNER_ACCOUNT_EMAIL, HETZNER_ACCOUNT_PASSWORD, and HETZNER_CUSTOMER_NUMBER to be set.
    """
    try:
        email = os.environ.get("HETZNER_ACCOUNT_EMAIL")
        password = os.environ.get("HETZNER_ACCOUNT_PASSWORD")
        customer_number = os.environ.get("HETZNER_CUSTOMER_NUMBER")
        if not email or not password:
            return "Error: HETZNER_ACCOUNT_EMAIL and HETZNER_ACCOUNT_PASSWORD environment variables must be set."
        if not customer_number:
            return "Error: HETZNER_CUSTOMER_NUMBER environment variable must be set."
        cl = _get_hetzner_client(ctx)
        data = await cl.get_invoice_details(params.usage_id)
        return json.dumps(data, indent=2)
    except Exception as e:
        return _handle_error(e)


# ---------------------------------------------------------------------------
# Entrypoint
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    mcp.run()
