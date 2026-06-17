"""Account/user reads via CustomerManagementService."""

from __future__ import annotations

from typing import Any

from openapi_client.models.customer.get_accounts_info_request import GetAccountsInfoRequest
from openapi_client.models.customer.get_user_request import GetUserRequest

from ..api.client import CUSTOMER, MsAdsClient
from ..domain.entities import AccountSummary
from . import as_list, first_attr


def get_user(client: MsAdsClient) -> Any:
    """Return the authenticated user object (carries the customer roles)."""
    resp = client.call(CUSTOMER, "get_user", GetUserRequest(user_id=None))
    return first_attr(resp, "User", "user")


def search_accounts(client: MsAdsClient) -> list[AccountSummary]:
    """List every advertising account reachable by the authenticated user."""
    resp = client.call(CUSTOMER, "get_user", GetUserRequest(user_id=None))
    roles = first_attr(resp, "CustomerRoles", "customer_roles")
    summaries: list[AccountSummary] = []
    seen_customers: set[Any] = set()
    for role in as_list(_unwrap(roles, "CustomerRole", "customer_role")):
        customer_id = first_attr(role, "CustomerId", "customer_id")
        if customer_id in seen_customers:
            continue
        seen_customers.add(customer_id)
        info = client.call(
            CUSTOMER,
            "get_accounts_info",
            GetAccountsInfoRequest(customer_id=customer_id, only_parent_accounts=False),
        )
        accounts = first_attr(info, "AccountsInfo", "accounts_info", "AccountInfo", default=info)
        for acc in as_list(_unwrap(accounts, "AccountInfo", "account_info")):
            summaries.append(AccountSummary.from_sdk(acc, customer_id))
    return summaries


def _unwrap(value: Any, *keys: str) -> Any:
    """Some REST array wrappers still nest under a typed key; unwrap if so, else passthrough."""
    if value is None:
        return None
    for key in keys:
        inner = getattr(value, key, None)
        if inner is not None:
            return inner
    return value
