"""Compact, agent-facing models for tool outputs.

These are *our* summaries, not the SDK's wire models (``openapi_client.models.*``). The SDK
models carry dozens of fields; tools return these trimmed views so the agent sees the
high-signal fields and stable shapes. Conversion from SDK objects happens in the services
layer via ``from_sdk`` helpers.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel

# The match types and statuses we accept/return, kept as Literals for agent clarity.
MatchType = Literal["Broad", "Phrase", "Exact"]
CampaignStatus = Literal["Active", "Paused"]


def _get(obj: Any, *names: str, default: Any = None) -> Any:
    """Read the first present attribute (msads models expose Pascal and snake_case)."""
    for name in names:
        val = getattr(obj, name, None)
        if val is not None:
            return val
    return default


class AccountHealth(BaseModel):
    """Result of the first call an agent should make: validates auth and reports mode."""

    ok: bool
    read_only: bool
    environment: str
    message: str
    user_name: str | None = None
    account_id: str | None = None
    customer_id: str | None = None


class AccountSummary(BaseModel):
    id: str
    name: str | None = None
    number: str | None = None
    customer_id: str | None = None
    status: str | None = None

    @classmethod
    def from_sdk(cls, acc: Any, customer_id: Any = None) -> AccountSummary:
        return cls(
            id=str(_get(acc, "Id", "id")),
            name=_get(acc, "Name", "name"),
            number=_get(acc, "Number", "number"),
            customer_id=str(customer_id) if customer_id is not None else None,
            status=_get(acc, "AccountLifeCycleStatus", "account_life_cycle_status"),
        )


class CampaignSummary(BaseModel):
    id: str
    name: str | None = None
    status: str | None = None
    campaign_type: str | None = None
    daily_budget: float | None = None
    budget_id: str | None = None

    @classmethod
    def from_sdk(cls, c: Any) -> CampaignSummary:
        ctype = _get(c, "CampaignType", "campaign_type")
        if isinstance(ctype, list):
            ctype = ", ".join(str(t) for t in ctype) or None
        return cls(
            id=str(_get(c, "Id", "id")),
            name=_get(c, "Name", "name"),
            status=_str_or_none(_get(c, "Status", "status")),
            campaign_type=str(ctype) if ctype is not None else None,
            daily_budget=_get(c, "DailyBudget", "daily_budget"),
            budget_id=_str_or_none(_get(c, "BudgetId", "budget_id")),
        )


class AdGroupSummary(BaseModel):
    id: str
    name: str | None = None
    status: str | None = None
    cpc_bid: float | None = None

    @classmethod
    def from_sdk(cls, ag: Any) -> AdGroupSummary:
        bid = _get(ag, "CpcBid", "cpc_bid")
        amount = _get(bid, "Amount", "amount") if bid is not None else None
        return cls(
            id=str(_get(ag, "Id", "id")),
            name=_get(ag, "Name", "name"),
            status=_str_or_none(_get(ag, "Status", "status")),
            cpc_bid=amount,
        )


class KeywordSummary(BaseModel):
    id: str
    text: str | None = None
    match_type: str | None = None
    status: str | None = None
    bid: float | None = None

    @classmethod
    def from_sdk(cls, kw: Any) -> KeywordSummary:
        bid = _get(kw, "Bid", "bid")
        amount = _get(bid, "Amount", "amount") if bid is not None else None
        return cls(
            id=str(_get(kw, "Id", "id")),
            text=_get(kw, "Text", "text"),
            match_type=_str_or_none(_get(kw, "MatchType", "match_type")),
            status=_str_or_none(_get(kw, "Status", "status")),
            bid=amount,
        )


class AdSummary(BaseModel):
    id: str
    ad_type: str | None = None
    status: str | None = None
    final_url: str | None = None

    @classmethod
    def from_sdk(cls, ad: Any) -> AdSummary:
        urls = _get(ad, "FinalUrls", "final_urls")
        final_url = None
        if urls is not None:
            items = _get(urls, "string", default=urls)
            if isinstance(items, list) and items:
                final_url = str(items[0])
        return cls(
            id=str(_get(ad, "Id", "id")),
            ad_type=_str_or_none(_get(ad, "Type", "type")),
            status=_str_or_none(_get(ad, "Status", "status")),
            final_url=final_url,
        )


class MutationResult(BaseModel):
    """Generic result for create/update tools."""

    ok: bool
    message: str
    ids: list[str] = []
    partial_errors: list[str] = []


class ReportRow(BaseModel):
    """One row of a downloaded performance report, as column -> value strings."""

    values: dict[str, str]


class ReportResult(BaseModel):
    """A completed performance report: its columns and parsed rows."""

    report_type: str
    date_range: str
    columns: list[str]
    row_count: int
    rows: list[ReportRow]


def _str_or_none(val: Any) -> str | None:
    """Stringify a value, unwrapping SDK enums to ``.value`` (not the ``Class.MEMBER`` repr)."""
    if val is None:
        return None
    return str(getattr(val, "value", val))
