# OpenCollective MCP Server

MCP server for interacting with OpenCollective's GraphQL API v2 and Hetzner Cloud invoices.

## Setup

### Authentication
- `OPENCOLLECTIVE_TOKEN` - Personal token from https://opencollective.com/dashboard/[your-account]/for-developers
- `HETZNER_ACCOUNT_EMAIL` - Your Hetzner account email
- `HETZNER_ACCOUNT_PASSWORD` - Your Hetzner account password
- `HETZNER_TOTP_SECRET` - TOTP secret (if 2FA enabled)
- `HETZNER_CUSTOMER_NUMBER` - Your Hetzner customer number (for invoice details)

Read-only OC operations work without authentication. Hetzner invoices require credentials.

### Running
```bash
# Direct
python -m opencollective_mcp

# Or via installed script
opencollective-mcp
```

### Claude Code Integration
Add to `~/.claude/claude_desktop_config.json` or project `.claude/settings.json`:
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
        "HETZNER_ACCOUNT_PASSWORD": "<your-hetzner-password>",
        "HETZNER_CUSTOMER_NUMBER": "<your-customer-number>"
      }
    }
  }
}
```

## Available Tools

### OpenCollective
| Tool | Description | Auth Required |
|------|-------------|---------------|
| `oc_get_account` | Get account info by slug | No |
| `oc_search_accounts` | Search accounts | No |
| `oc_get_logged_in_account` | Get current authenticated user | Yes |
| `oc_edit_account` | Edit account profile | Yes |
| `oc_get_members` | List members/backers | No |
| `oc_list_expenses` | List expenses with filters | No |
| `oc_get_expense` | Get expense details | No |
| `oc_create_expense` | Submit new expense | Yes |
| `oc_edit_expense` | Edit existing expense | Yes |
| `oc_delete_expense` | Delete expense | Yes |
| `oc_process_expense` | Approve/reject/pay expense | Yes |
| `oc_list_transactions` | List transactions (ledger) | No |
| `oc_execute_graphql` | Run raw GraphQL | Depends |

### Hetzner Cloud
| Tool | Description | Auth Required |
|------|-------------|---------------|
| `hetzner_list_invoices` | List all Hetzner invoices (paginated) | Yes |
| `hetzner_get_invoice` | Get specific invoice by ID | Yes |
| `hetzner_get_latest_invoice` | Get the most recent invoice | Yes |

## Monthly Bookkeeping Workflow
1. `hetzner_get_latest_invoice` - Fetch the latest Hetzner invoice
2. `oc_create_expense` - Submit it as an INVOICE expense to the goingdark collective
   - Use the invoice amount, date, and description from the Hetzner data
   - Tag with `["hetzner", "hosting"]` for categorization

## Collective Info
- Primary collective: `goingdark` (slug)
- Currency: EUR

## Project Structure
```
src/opencollective_mcp/
  __init__.py          # Package init
  __main__.py          # python -m entrypoint
  server.py            # MCP server with all tools (16 tools)
  client.py            # OpenCollective GraphQL HTTP client
  queries.py           # All GraphQL query/mutation strings
  hetzner.py           # Hetzner Cloud API client
```
