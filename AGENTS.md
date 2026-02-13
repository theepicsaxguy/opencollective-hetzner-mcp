# OpenCollective MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io/) server that gives AI agents programmatic access to the [OpenCollective GraphQL API v2](https://graphql-docs-v2.opencollective.com/), [Hetzner Cloud](https://docs.hetzner.cloud/) invoices, and [Cloudflare](https://www.cloudflare.com/) billing. Built with Python, [FastMCP](https://github.com/modelcontextprotocol/python-sdk), and [httpx](https://www.python-httpx.org/).

The primary use case is automated monthly bookkeeping: fetching hosting invoices from Hetzner and Cloudflare, then submitting them as expenses to an OpenCollective collective -- but the server exposes the full range of OpenCollective operations so any agent can manage collectives, expenses, members, and transactions without manual intervention.

---

## Architecture

```
src/opencollective_mcp/
  __init__.py              Package marker
  __main__.py              `python -m opencollective_mcp` entrypoint
  server.py                FastMCP server -- all 22 tools, input models, lifespan
  client.py                Async GraphQL client for OpenCollective API v2
  queries.py               GraphQL query/mutation strings (organized by domain)
  hetzner.py               Hetzner client wrapper (uses browser automation)
  hetzner_browser.py       Browser automation for Hetzner Accounts login and invoice retrieval
  cloudflare.py            Cloudflare billing client (uses REST API)
```

### Design decisions

**Separation of concerns.** The GraphQL client (`client.py`) knows nothing about MCP. The query strings (`queries.py`) are plain constants. The Hetzner client (`hetzner.py`) is its own module. The server (`server.py`) wires them together through FastMCP tools. Any piece can be swapped, tested, or reused independently.

**No hardcoded slugs or IDs.** Every tool accepts the account slug / ID as a parameter. The server itself stores no state about which collective it operates on.

**Authenticated and unauthenticated.** Read-only OpenCollective queries (account info, public expenses, transactions, members) work without a token. Write operations and Hetzner calls require their respective tokens via environment variables.

**Escape hatch.** `oc_execute_graphql` accepts any raw GraphQL string, so agents can run operations not covered by the dedicated tools without waiting for a code change.

**Pydantic validation.** All tool inputs use Pydantic v2 models with field constraints, validators, and descriptive metadata. Invalid input is rejected before any API call is made.

### How it was built

1. **Schema introspection.** The OpenCollective GraphQL schema was introspected live at `https://api.opencollective.com/graphql/v2` using `__schema` and `__type` queries to discover all available queries, mutations, input types, enums, and field shapes.

2. **Hetzner invoice retrieval via browser automation.** Since Hetzner does not provide a public API for billing/invoices, we use Playwright to automate the web interface at `accounts.hetzner.com/invoice`. This logs in with your email/password and extracts invoice data from the HTML table.

3. **Cloudflare billing retrieval via API.** Cloudflare provides a deprecated but functional `/user/billing/history` endpoint that returns billing events with amounts and dates. While not a true invoice API (no PDFs), it provides the essential cost and date data needed for bookkeeping.

4. **FastMCP wiring.** Each tool is registered with `@mcp.tool()` including annotations (`readOnlyHint`, `destructiveHint`, etc.) so MCP clients can reason about safety. A lifespan context manager initializes both API clients once at startup and injects them into tool handlers via the MCP context.

### API references

| Service | Endpoint | Auth header | Docs |
|---------|----------|-------------|------|
| OpenCollective GraphQL v2 | `https://api.opencollective.com/graphql/v2` | `Personal-Token: <token>` | [graphql-docs-v2.opencollective.com](https://graphql-docs-v2.opencollective.com/) |
| Hetzner Cloud | `https://api.hetzner.cloud/v1` | `Authorization: Bearer <token>` | [docs.hetzner.cloud](https://docs.hetzner.cloud/) |
| Cloudflare API | `https://api.cloudflare.com/client/v4` | `Authorization: Bearer <token>` | [developers.cloudflare.com/api](https://developers.cloudflare.com/api/) |

---

## Setup

### Prerequisites

- Python >= 3.10
- `mcp` >= 1.0.0, `httpx` >= 0.24.0, `pydantic` >= 2.0.0, `playwright` >= 1.40.0, `pyotp` >= 2.9.0

Install dependencies:

```bash
pip install mcp httpx pydantic playwright pyotp
playwright install chromium
```

Or install the project itself:

```bash
pip install -e .
```

### Environment variables

| Variable | Required for | How to get it |
|----------|-------------|---------------|
| `OPENCOLLECTIVE_TOKEN` | Write operations (create/edit expenses, edit account) | [OpenCollective dashboard](https://opencollective.com/dashboard) > For Developers > Personal Tokens |
| `HETZNER_ACCOUNT_EMAIL` | Hetzner invoice tools | Your Hetzner account login email |
| `HETZNER_ACCOUNT_PASSWORD` | Hetzner invoice tools | Your Hetzner account password |
| `HETZNER_TOTP_SECRET` | Hetzner invoice tools (if 2FA enabled) | Your TOTP secret key from when you set up 2FA |
| `CLOUDFLARE_API_TOKEN` | Cloudflare billing tools | [Cloudflare dashboard](https://dash.cloudflare.com) > My Profile > API Tokens > Create Token with "Billing:Read" permission |

**Getting your TOTP secret:** If you have 2FA enabled on your Hetzner account, you'll need your TOTP secret key for automated login. This was shown as a "Secret key" or "Setup key" when you first enabled 2FA. If you don't have it, you'll need to disable and re-enable 2FA to get a new secret, or use a recovery code.

**Note:** The `HETZNER_API_TOKEN` is no longer used for invoice retrieval since Hetzner doesn't provide a public API for billing. We now use browser automation with your account credentials instead.

Neither OpenCollective nor Hetzner token is required for read-only OpenCollective queries.

### Running the server

```bash
# Via module
python -m opencollective_mcp

# Via installed script
opencollective-mcp
```

The server communicates over **stdio** (standard MCP transport for local tools).

### Claude Code / Claude Desktop integration

Add to your MCP configuration (`~/.claude.json`, `.claude/settings.json`, or Claude Desktop config):

```json
{
  "mcpServers": {
    "opencollective": {
      "command": "python",
      "args": ["-m", "opencollective_mcp"],
      "cwd": "/path/to/Opencollective-MCP/src",
      "env": {
        "OPENCOLLECTIVE_TOKEN": "<your-oc-token>",
        "HETZNER_ACCOUNT_EMAIL": "<your-hetzner-email>",
        "HETZNER_ACCOUNT_PASSWORD": "<your-hetzner-password>"
      }
    }
  }
}
```

---

## Tools reference

### OpenCollective -- Accounts

#### `oc_get_account`
Get detailed info about any account by slug. Returns profile, balance, yearly budget, total received/spent, social links.

```
slug: "goingdark"
```

#### `oc_search_accounts`
Search across all OpenCollective accounts. Filter by type: `COLLECTIVE`, `ORGANIZATION`, `INDIVIDUAL`, `FUND`, `PROJECT`, `EVENT`.

```
search_term: "open source"
account_type: "COLLECTIVE"
limit: 10
```

#### `oc_get_logged_in_account`
Get the currently authenticated user's account info. Requires `OPENCOLLECTIVE_TOKEN`.

#### `oc_edit_account`
Update an account's profile fields (name, description, tags, currency, etc.). Requires the account `id` (get it from `oc_get_account` first).

```
id: "abc123-..."
description: "Updated description"
tags: ["privacy", "security"]
```

#### `oc_edit_account_setting`
Edit account settings like monthly spending limits or other configuration.

```
slug: "goingdark"
key: "expensesMonthlyLimit"
value: "80"
```

Common keys: `expensesMonthlyLimit`, `VIRTUAL_CARDS_MAX_MONTHLY_AMOUNT`, `goals`

#### `oc_set_budget`
Set the yearly budget goal for a collective. Converts EUR to cents automatically.

```
slug: "goingdark"
amount: 800
title: "Yearly Budget"
```

Note: Pass amount in EUR (800 = €800), not cents. The tool converts automatically.
Requires token with 'account' scope.

### OpenCollective -- Members

#### `oc_get_members`
List members and backers of a collective with roles, donation totals, and profile info.

```
slug: "goingdark"
limit: 50
```

### OpenCollective -- Expenses

#### `oc_list_expenses`
List expenses with rich filtering: by account, payee, status, type, tags, date range, search.

```
account_slug: "goingdark"
status: ["APPROVED", "PAID"]
expense_type: "INVOICE"
date_from: "2025-01-01"
limit: 50
```

#### `oc_get_expense`
Get full details of a single expense by ID or legacy ID.

```
id: "abc123-..."
```

#### `oc_create_expense`
Submit a new expense. This is the core tool for bookkeeping automation.

```
account_slug: "goingdark"
description: "Hetzner Cloud - January 2025"
expense_type: "INVOICE"
payee_slug: "your-username"
currency: "EUR"
tags: ["hetzner", "hosting"]
items: [
  {
    "description": "Cloud server CX22",
    "amount_cents": 1184,
    "currency": "EUR",
    "incurred_at": "2025-01-31"
  }
]
```

**Expense types:** `INVOICE`, `RECEIPT`, `FUNDING_REQUEST`, `GRANT`, `UNCLASSIFIED`, `CHARGE`

**Payout methods:** `OTHER` (default), `PAYPAL`, `BANK_ACCOUNT`, `ACCOUNT_BALANCE`, `CREDIT_CARD`, `STRIPE`

**Recurring:** Set `recurring_interval` to `MONTH`, `QUARTER`, or `YEAR` to auto-create.

#### `oc_edit_expense`
Modify an existing expense's description, tags, type, private message, invoice info, or reference.

#### `oc_delete_expense`
Delete an expense by ID or legacy ID. Destructive operation.

#### `oc_process_expense`
Change an expense's workflow status. Available actions:
- `APPROVE` / `UNAPPROVE` / `REQUEST_RE_APPROVAL`
- `REJECT`
- `PAY` / `MARK_AS_UNPAID`
- `SCHEDULE_FOR_PAYMENT` / `UNSCHEDULE_PAYMENT`
- `MARK_AS_SPAM` / `MARK_AS_INCOMPLETE`
- `HOLD` / `RELEASE`

### OpenCollective -- Transactions

#### `oc_list_transactions`
Query the ledger. Shows credits/debits with amounts, linked expenses/orders, and counterparty info. Filter by type (`CREDIT`/`DEBIT`), date range, kind (`CONTRIBUTION`, `EXPENSE`, `ADDED_FUNDS`, `HOST_FEE`, etc.), and search.

```
account_slug: "goingdark"
transaction_type: "DEBIT"
date_from: "2025-01-01"
date_to: "2025-01-31"
```

### OpenCollective -- Raw GraphQL

#### `oc_execute_graphql`
Execute any GraphQL query or mutation directly. Escape hatch for operations not covered by dedicated tools.

```
query: "{ account(slug: \"goingdark\") { id name stats { balance { valueInCents currency } } } }"
```

### Hetzner Cloud

#### `hetzner_list_invoices`
List all invoices with pagination. Standard Hetzner pagination: `page` (default 1), `per_page` (default 25, max 50).

#### `hetzner_get_invoice`
Get a single invoice by ID.

#### `hetzner_get_latest_invoice`
Convenience tool: fetches the most recent invoice. Designed for the monthly bookkeeping workflow.

### Cloudflare

#### `cloudflare_list_invoices`
List billing history with pagination. Uses the deprecated but functional `/user/billing/history` endpoint. Returns cost, date, and type for each billing item. By default, automatically converts USD amounts to EUR using historical exchange rates from the European Central Bank (via Frankfurter API).

**Parameters:**
- `page`: Page number (default: 1)
- `per_page`: Items per page, max 50 (default: 25)
- `convert_to_eur`: Whether to convert USD to EUR (default: true)

**Returns:** Each invoice includes:
- `amount`: Original amount (usually USD)
- `currency`: Original currency code
- `amount_eur`: Converted EUR amount (when conversion enabled)
- `amount_cents_eur`: EUR amount in cents (for OpenCollective)
- `exchange_rate`: Rate used for conversion
- `rate_date`: Date the exchange rate was fetched

#### `cloudflare_get_invoice`
Get a specific billing item by ID. Supports automatic EUR conversion via `convert_to_eur` parameter (default: true).

#### `cloudflare_get_latest_invoice`
Convenience tool: fetches the most recent billing item. Designed for the monthly bookkeeping workflow. Automatically converts USD to EUR by default. Returns `amount_cents_eur` ready for direct use with OpenCollective.

---

## Workflows

### Monthly Hetzner expense submission

The primary automation this server enables:

1. **Fetch** the latest Hetzner invoice: `hetzner_get_latest_invoice`
2. **Extract** the total amount, date, and invoice number from the response
3. **Submit** it to OpenCollective: `oc_create_expense` with:
   - `account_slug: "goingdark"`
   - `expense_type: "INVOICE"`
   - `tags: ["hetzner", "hosting"]`
   - Amount and date from step 2

This works even with a negative collective balance -- the expense is recorded for bookkeeping and will be paid when funds are available.

### Monthly Cloudflare expense submission

Cloudflare bills in USD, but the tools automatically convert to EUR using historical exchange rates from the European Central Bank (via Frankfurter API):

1. **Fetch** the latest Cloudflare billing item: `cloudflare_get_latest_invoice`
2. **Extract** the data from the response:
   - `amount_eur`: Converted EUR amount (e.g., "2.92")
   - `amount_cents_eur`: EUR amount in cents for OpenCollective (e.g., 292)
   - `exchange_rate`: Rate used for conversion
   - `date`: Invoice date
3. **Submit** it to OpenCollective: `oc_create_expense` with:
   - `account_slug: "goingdark"`
   - `expense_type: "INVOICE"`
   - `tags: ["cloudflare", "hosting", "cdn"]`
   - `amount_cents`: Use `amount_cents_eur` from step 2
   - Date from step 2

**Note:** EUR conversion is enabled by default. Set `convert_to_eur: false` to get original USD amounts only.

### Check collective health

1. `oc_get_account` with slug `goingdark` to see balance and stats
2. `oc_list_transactions` to review recent activity
3. `oc_get_members` to see backers

### Expense management

1. `oc_list_expenses` to find expenses by status/type/date
2. `oc_process_expense` to approve or reject
3. `oc_edit_expense` to update metadata

---

## Extending the server

### Adding a new OpenCollective tool

1. Add the GraphQL query/mutation string to `queries.py`
2. Add a Pydantic input model to `server.py`
3. Add a `@mcp.tool()` decorated async function to `server.py`
4. Use `_get_client(ctx)` to get the GraphQL client
5. Use `_handle_error(e)` for consistent error formatting

The OC GraphQL schema can be introspected at any time:

```bash
curl -s -X POST https://api.opencollective.com/graphql/v2 \
  -H "Content-Type: application/json" \
  -d '{"query":"{ __schema { queryType { fields { name } } } }"}' | python3 -m json.tool
```

### Adding a new external service

Follow the pattern of `hetzner.py`:

1. Create a new client module (e.g. `newservice.py`) with an async client class
2. Import it in `server.py`
3. Add the client to the `app_lifespan` yield dict with its env var token
4. Add a `_get_newservice_client(ctx)` helper
5. Add input models and `@mcp.tool()` functions

### Available OC GraphQL operations

Queries: `account`, `accounts`, `expense`, `expenses`, `transactions`, `order`, `orders`, `loggedInAccount`, `me`, `collective`, `host`, `hosts`, `individual`, `organization`, `event`, `fund`, `project`, `search`, `tagStats`, `tier`, `update`, `updates`

Mutations: `createExpense`, `editExpense`, `deleteExpense`, `processExpense`, `editAccount`, `editAccountSetting`, `createComment`, `editComment`, `deleteComment`, `createOrder`, `cancelOrder`, `updateOrder`, `createUpdate`, `editUpdate`, `publishUpdate`, `createWebhook`, `updateWebhook`, `deleteWebhook`, `setTags`, `updateSocialLinks`, and many more (120+ total).

Run the introspection query above to see the full current list.
