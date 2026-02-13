# OpenCollective MCP Server

A [Model Context Protocol](https://modelcontextprotocol.io/) server that gives AI agents programmatic access to [OpenCollective](https://opencollective.com/) and [Hetzner Cloud](https://www.hetzner.com/) — enabling automated bookkeeping, collective management, and invoice handling without manual intervention.

## What is it?

This MCP server exposes 19 tools that let AI agents interact with:

- **OpenCollective GraphQL API v2** — Manage collectives, submit expenses, process payments, query transactions, and handle members
- **Hetzner Cloud invoices** — Automatically fetch, parse, and reconcile hosting invoices

### The Problem

If you run an OpenCollective-backed project with infrastructure on Hetzner, you face a tedious monthly ritual:

1. Log into Hetzner → navigate to invoices → download the PDF
2. Manually extract the amount, date, and line items
3. Log into OpenCollective → create a new expense → copy-paste the data
4. Submit and wait for approval

Repeat every month. Forever.

**This MCP automates it.**

## Who is it for?

- **Open collective maintainers** who want to automate expense workflows
- **DevOps engineers** running infrastructure on Hetzner who track costs via OpenCollective
- **AI developers** building agents that need to manage budgets, expenses, or financial reporting
- **Bookkeepers** tired of copy-pasting invoice data between systems

## What can it do?

### OpenCollective Operations (13 tools)

| Tool | What it does |
|------|--------------|
| `oc_get_account` | Get detailed info about any collective (balance, stats, social links) |
| `oc_search_accounts` | Search across all OpenCollective accounts |
| `oc_get_logged_in_account` | Get the authenticated user's account |
| `oc_edit_account` | Update collective profile (name, description, tags, currency) |
| `oc_get_members` | List members, backers, and their donation totals |
| `oc_list_expenses` | Query expenses with rich filters (status, type, date, tags) |
| `oc_get_expense` | Get full expense details by ID |
| `oc_create_expense` | Submit new expenses (INVOICE, RECEIPT, GRANT, etc.) |
| `oc_edit_expense` | Modify existing expenses |
| `oc_delete_expense` | Remove expenses |
| `oc_process_expense` | Approve, reject, pay, hold, or release expenses |
| `oc_list_transactions` | Query the ledger (credits/debits, linked expenses) |
| `oc_execute_graphql` | Escape hatch for any GraphQL operation |

### Hetzner Operations (6 tools)

| Tool | What it does |
|------|--------------|
| `hetzner_list_invoices` | List all invoices (paginated) |
| `hetzner_get_invoice` | Get a specific invoice by ID |
| `hetzner_get_latest_invoice` | Fetch the most recent invoice |
| `hetzner_get_invoice_pdf` | Download invoice as PDF (base64) |
| `hetzner_parse_invoice_pdf` | Extract structured data from invoice PDF |
| `hetzner_get_invoice_details` | Get line-item breakdown from usage portal |

## The Monthly Bookkeeping Workflow

```python
# 1. Fetch the latest Hetzner invoice
invoice = hetzner_get_latest_invoice()

# 2. Submit it as an expense to your collective
oc_create_expense(
    account_slug="my-collective",
    description=f"Hetzner Cloud - {invoice['date']}",
    expense_type="INVOICE",
    payee_slug="my-org",
    items=[{
        "description": f"Cloud services - {invoice['date']}",
        "amount_cents": invoice['amount_cents'],
        "currency": "EUR"
    }],
    tags=["hetzner", "hosting"]
)
```

That's it. One agent prompt = one booked expense.

## What it's NOT

- **Not a replacement for human judgment** — Expenses still need approval based on your collective's policies
- **Not a financial advisory tool** — It moves data, not money; you control the payouts
- **Not limited to Hetzner** — The `oc_execute_graphql` tool lets you run any OpenCollective operation, so you can manage Stripe payouts, Wise transfers, or budget forecasting
- **Not a GUI** — It's a backend for AI agents; use the OpenCollective dashboard for manual tasks

## Quick Start

### 1. Clone and install

```bash
git clone https://github.com/your-org/opencollective-mcp.git
cd opencollective-mcp
pip install -e .
```

### 2. Configure environment

Copy `.env.example` to `.env` and fill in:

```bash
cp .env.example .env
# Edit .env with your credentials
```

| Variable | Required for | How to get it |
|----------|-------------|---------------|
| `OPENCOLLECTIVE_TOKEN` | Write operations | [OpenCollective dashboard](https://opencollective.com/dashboard) → For Developers → Personal Tokens |
| `HETZNER_ACCOUNT_EMAIL` | Invoice tools | Your Hetzner account email |
| `HETZNER_ACCOUNT_PASSWORD` | Invoice tools | Your Hetzner password |
| `HETZNER_TOTP_SECRET` | Invoice tools (if 2FA) | Shown when you enable 2FA |

### 3. Run the server

```bash
# Direct
python -m opencollective_mcp

# Or via installed script
opencollective-mcp
```

### 4. Connect to Claude Desktop

Add to your `~/.claude.json`:

```json
{
  "mcpServers": {
    "opencollective": {
      "command": "python",
      "args": ["-m", "opencollective_mcp"],
      "env": {
        "OPENCOLLECTIVE_TOKEN": "your-token",
        "HETZNER_ACCOUNT_EMAIL": "you@example.com",
        "HETZNER_ACCOUNT_PASSWORD": "your-password"
      }
    }
  }
}
```

## Why build this?

Because **infrastructure costs should be visible, automated, and auditable** — exactly what OpenCollective provides for open source projects.

We built this to solve our own bookkeeping pain: tracking Hetzner hosting costs for [Going Dark](https://opencollective.com/goingdark) and automatically submitting them as expenses each month. Now our AI agent does it.

If you run a collective with cloud infrastructure, this saves you 15–30 minutes every month — and eliminates human error from manual data entry.

## License

MIT

---

Built with [FastMCP](https://github.com/modelcontextprotocol/python-sdk), [httpx](https://www.python-httpx.org/), and [Playwright](https://playwright.dev/).
