"""GraphQL query and mutation strings for OpenCollective API v2.

Organized by domain: accounts, expenses, transactions, members.
Each constant is a ready-to-use GraphQL operation string.
"""

# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

GET_ACCOUNT = """
query GetAccount($slug: String!) {
  account(slug: $slug) {
    id
    slug
    name
    legalName
    type
    description
    longDescription
    currency
    tags
    imageUrl
    backgroundImageUrl
    createdAt
    stats {
      balance { valueInCents currency }
      yearlyBudget { valueInCents currency }
      totalAmountSpent { valueInCents currency }
      totalAmountReceived { valueInCents currency }
    }
    socialLinks { type url }
  }
}
"""

SEARCH_ACCOUNTS = """
query SearchAccounts($searchTerm: String, $limit: Int!, $offset: Int!, $type: [AccountType]) {
  accounts(searchTerm: $searchTerm, limit: $limit, offset: $offset, type: $type) {
    totalCount
    nodes {
      id
      slug
      name
      type
      description
      currency
      imageUrl
    }
  }
}
"""

GET_LOGGED_IN_ACCOUNT = """
query GetLoggedInAccount {
  loggedInAccount {
    id
    slug
    name
    legalName
    type
    email
    currency
    stats {
      balance { valueInCents currency }
    }
  }
}
"""

# ---------------------------------------------------------------------------
# Members / Backers
# ---------------------------------------------------------------------------

GET_MEMBERS = """
query GetMembers($slug: String!, $limit: Int!, $offset: Int!) {
  account(slug: $slug) {
    members(limit: $limit, offset: $offset) {
      totalCount
      nodes {
        id
        role
        since
        totalDonations { valueInCents currency }
        account {
          id
          slug
          name
          type
          imageUrl
        }
      }
    }
  }
}
"""

# ---------------------------------------------------------------------------
# Expenses
# ---------------------------------------------------------------------------

EXPENSE_FRAGMENT = """
fragment ExpenseFields on Expense {
  id
  legacyId
  description
  longDescription
  reference
  type
  status
  currency
  createdAt
  incurredAt
  tags
  privateMessage
  invoiceInfo
  amountV2 { valueInCents currency }
  account { id slug name }
  payee { id slug name }
  createdByAccount { id slug name }
  payoutMethod { id type name }
  items { id description amountV2 { valueInCents currency } url incurredAt }
  recurringExpense { id interval endsAt }
}
"""

GET_EXPENSE = f"""
{EXPENSE_FRAGMENT}
query GetExpense($id: String, $legacyId: Int) {{
  expense(expense: {{ id: $id, legacyId: $legacyId }}) {{
    ...ExpenseFields
  }}
}}
"""

LIST_EXPENSES = f"""
{EXPENSE_FRAGMENT}
query ListExpenses(
  $account: AccountReferenceInput
  $fromAccount: AccountReferenceInput
  $status: [ExpenseStatusFilter]
  $type: ExpenseType
  $tag: [String]
  $limit: Int!
  $offset: Int!
  $dateFrom: DateTime
  $dateTo: DateTime
  $searchTerm: String
  $orderBy: ChronologicalOrderInput
) {{
  expenses(
    account: $account
    fromAccount: $fromAccount
    status: $status
    type: $type
    tag: $tag
    limit: $limit
    offset: $offset
    dateFrom: $dateFrom
    dateTo: $dateTo
    searchTerm: $searchTerm
    orderBy: $orderBy
  ) {{
    totalCount
    nodes {{
      ...ExpenseFields
    }}
  }}
}}
"""

CREATE_EXPENSE = f"""
{EXPENSE_FRAGMENT}
mutation CreateExpense(
  $expense: ExpenseCreateInput!
  $account: AccountReferenceInput!
) {{
  createExpense(expense: $expense, account: $account) {{
    ...ExpenseFields
  }}
}}
"""

EDIT_EXPENSE = f"""
{EXPENSE_FRAGMENT}
mutation EditExpense($expense: ExpenseUpdateInput!) {{
  editExpense(expense: $expense) {{
    ...ExpenseFields
  }}
}}
"""

DELETE_EXPENSE = """
mutation DeleteExpense($id: String, $legacyId: Int) {
  deleteExpense(expense: { id: $id, legacyId: $legacyId }) {
    id
  }
}
"""

PROCESS_EXPENSE = f"""
{EXPENSE_FRAGMENT}
mutation ProcessExpense(
  $id: String
  $legacyId: Int
  $action: ExpenseProcessAction!
  $message: String
) {{
  processExpense(
    expense: {{ id: $id, legacyId: $legacyId }}
    action: $action
    message: $message
  ) {{
    ...ExpenseFields
  }}
}}
"""

# ---------------------------------------------------------------------------
# Transactions / Ledger
# ---------------------------------------------------------------------------

LIST_TRANSACTIONS = """
query ListTransactions(
  $account: [AccountReferenceInput!]
  $type: TransactionType
  $limit: Int!
  $offset: Int!
  $dateFrom: DateTime
  $dateTo: DateTime
  $searchTerm: String
  $kind: [TransactionKind]
  $orderBy: ChronologicalOrderInput
) {
  transactions(
    account: $account
    type: $type
    limit: $limit
    offset: $offset
    dateFrom: $dateFrom
    dateTo: $dateTo
    searchTerm: $searchTerm
    kind: $kind
    orderBy: $orderBy
  ) {
    totalCount
    nodes {
      id
      legacyId
      type
      kind
      description
      createdAt
      amount { valueInCents currency }
      netAmount { valueInCents currency }
      account { id slug name }
      oppositeAccount { id slug name }
      expense { id legacyId description }
      order { id legacyId }
    }
  }
}
"""

# ---------------------------------------------------------------------------
# Account editing
# ---------------------------------------------------------------------------

EDIT_ACCOUNT = """
mutation EditAccount($account: AccountUpdateInput!) {
  editAccount(account: $account) {
    id
    slug
    name
    legalName
    description
    longDescription
    tags
    currency
    socialLinks { type url }
  }
}
"""

EDIT_ACCOUNT_SETTING = """
mutation EditAccountSetting($account: AccountReferenceInput!, $key: String!, $value: JSON!) {
  editAccountSetting(account: $account, key: $key, value: $value) {
    id
    slug
    name
  }
}
"""
