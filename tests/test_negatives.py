"""Negative-keyword flows build the right EntityNegativeKeyword graph and parse nested results."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from microsoft_ads_mcp.services import negatives


class _FakeClient:
    account_id = "123"

    def __init__(self, resp: Any) -> None:
        self._resp = resp
        self.calls: list[tuple[str, str, Any]] = []

    def call(self, service: str, method: str, request: Any) -> Any:
        self.calls.append((service, method, request))
        return self._resp

    # add_negative_keywords_to_entities reads the raw JSON via call_raw; first_attr is
    # dict-or-object tolerant, so delegate to the same fixed response.
    def call_raw(self, service: str, method: str, request: Any) -> Any:
        return self.call(service, method, request)


def test_add_negatives_builds_entity_graph_and_flattens_ids() -> None:
    resp = SimpleNamespace(
        negative_keyword_ids=[SimpleNamespace(ids=["11", "12"])],
        nested_partial_errors=[],
    )
    client = _FakeClient(resp)
    result = negatives.add_negative_keywords(
        client,
        entity_id="487928625",
        entity_type="Campaign",
        keywords=["astound login", "astound pay bill"],
        match_type="Phrase",
    )
    assert result.ok and result.ids == ["11", "12"]
    _, method, request = client.calls[0]
    assert method == "add_negative_keywords_to_entities"
    entity = request.entity_negative_keywords[0]
    assert entity.entity_id == "487928625" and entity.entity_type == "Campaign"
    nk = entity.negative_keywords[0]
    assert nk.type == "NegativeKeyword"
    assert nk.text == "astound login"
    assert nk.match_type.value == "Phrase"


def test_get_negatives_flattens_per_entity() -> None:
    resp = SimpleNamespace(
        entity_negative_keywords=[
            SimpleNamespace(
                entity_id="1",
                negative_keywords=[
                    SimpleNamespace(id="11", text="astound login", match_type="Exact"),
                    SimpleNamespace(id="12", text="astound outage", match_type="Phrase"),
                ],
            )
        ]
    )
    client = _FakeClient(resp)
    out = negatives.get_negative_keywords(client, entity_ids=["1"], entity_type="Campaign")
    assert [n.text for n in out] == ["astound login", "astound outage"]
    assert out[0].id == "11" and out[0].entity_id == "1"


def test_get_negatives_adgroup_requires_parent() -> None:
    client = _FakeClient(SimpleNamespace(entity_negative_keywords=[]))
    with pytest.raises(ValueError, match="parent_entity_id"):
        negatives.get_negative_keywords(client, entity_ids=["7"], entity_type="AdGroup")


def test_remove_negatives_targets_ids() -> None:
    client = _FakeClient(SimpleNamespace(nested_partial_errors=[]))
    result = negatives.remove_negative_keywords(
        client, entity_id="1", entity_type="Campaign", keyword_ids=["11", "12"]
    )
    assert result.ok and result.ids == ["11", "12"]
    _, method, request = client.calls[0]
    assert method == "delete_negative_keywords_from_entities"
    nk = request.entity_negative_keywords[0].negative_keywords[0]
    assert nk.id == "11" and nk.type == "NegativeKeyword"


def test_invalid_entity_type_rejected() -> None:
    client = _FakeClient(SimpleNamespace())
    with pytest.raises(ValueError, match="Campaign"):
        negatives.add_negative_keywords(
            client, entity_id="1", entity_type="Account", keywords=["x"]
        )


def test_add_negatives_null_id_surfaces_partial_error() -> None:
    # A rejected negative comes back with a null nested id + NestedPartialErrors; call_raw +
    # dict-aware helpers must surface it as ok=false, not crash on the non-nullable id. Script the
    # raw JSON dict (Pascal keys) call_raw really returns.
    raw = {
        "NegativeKeywordIds": [{"Ids": [None]}],
        "NestedPartialErrors": [
            {"BatchErrors": [{"Code": "DuplicateNegativeKeyword", "Message": "dup"}]}
        ],
    }
    client = _FakeClient(raw)
    result = negatives.add_negative_keywords(
        client, entity_id="1", entity_type="Campaign", keywords=["astound login"]
    )
    assert result.ok is False and result.ids == []
    assert result.partial_errors == ["DuplicateNegativeKeyword: dup"]
