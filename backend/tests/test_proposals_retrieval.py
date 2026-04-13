"""
Unit and property-based tests for proposals.py retrieval paths.

Covers:
  - Unit tests: list merge, empty list, 404 for unknown ID
  - Property 12: GET /proposals returns exactly N+M records
  - Property 13: GET /proposals/{id} returns full record for any existing ID
  - Property 11 (GET path): GET /proposals/{id} returns 404 for unknown ID
"""

import json
import sys
import os
from unittest.mock import MagicMock, patch

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Make backend/ importable without installing the package
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_draft(proposal_id: str, created_at: str = "2024-01-01T00:00:00Z") -> dict:
    return {
        "proposalId": proposal_id,
        "status": "PENDING",
        "createdAt": created_at,
        "surveyNotes": "some notes",
        "aiGeneratedSections": [],
        "version": 1,
    }


def _make_approved(proposal_id: str, approved_at: str = "2024-06-01T00:00:00Z") -> dict:
    return {
        "proposalId": proposal_id,
        "status": "APPROVED",
        "approvedAt": approved_at,
        "finalSections": [],
        "approvedBy": "user@example.com",
        "version": 1,
    }


def _build_mock_dynamodb(draft_items: list, approved_items: list):
    """Return a mock boto3 dynamodb resource wired to the given items."""
    mock_dynamodb = MagicMock()

    draft_table = MagicMock()
    approved_table = MagicMock()

    # scan returns all items
    draft_table.scan.return_value = {"Items": draft_items}
    approved_table.scan.return_value = {"Items": approved_items}

    # get_item looks up by proposalId
    def draft_get_item(Key):
        pid = Key["proposalId"]
        match = next((i for i in draft_items if i["proposalId"] == pid), None)
        return {"Item": match} if match else {}

    def approved_get_item(Key):
        pid = Key["proposalId"]
        match = next((i for i in approved_items if i["proposalId"] == pid), None)
        return {"Item": match} if match else {}

    draft_table.get_item.side_effect = draft_get_item
    approved_table.get_item.side_effect = approved_get_item

    def table_factory(name):
        import proposals as p
        if name == p.DRAFT_TABLE_NAME:
            return draft_table
        return approved_table

    mock_dynamodb.Table.side_effect = table_factory
    return mock_dynamodb


def _invoke_list(draft_items, approved_items):
    """Call handle_list_proposals with mocked DynamoDB."""
    import proposals as p
    with patch.object(p, "dynamodb", _build_mock_dynamodb(draft_items, approved_items)):
        return p.handle_list_proposals()


def _invoke_get(proposal_id, draft_items, approved_items):
    """Call handle_get_proposal with mocked DynamoDB."""
    import proposals as p
    with patch.object(p, "dynamodb", _build_mock_dynamodb(draft_items, approved_items)):
        return p.handle_get_proposal(proposal_id)


# ===========================================================================
# Unit Tests — Task 2.1
# ===========================================================================

class TestListProposals:
    def test_merges_drafts_and_approved(self):
        drafts = [_make_draft("d1"), _make_draft("d2")]
        approved = [_make_approved("a1")]

        resp = _invoke_list(drafts, approved)
        body = json.loads(resp["body"])

        assert resp["statusCode"] == 200
        ids = {item["proposalId"] for item in body}
        assert ids == {"d1", "d2", "a1"}
        assert len(body) == 3

    def test_empty_list_when_both_tables_empty(self):
        resp = _invoke_list([], [])
        body = json.loads(resp["body"])

        assert resp["statusCode"] == 200
        assert body == []

    def test_only_drafts(self):
        drafts = [_make_draft("d1")]
        resp = _invoke_list(drafts, [])
        body = json.loads(resp["body"])

        assert len(body) == 1
        assert body[0]["proposalId"] == "d1"
        assert body[0]["status"] == "PENDING"

    def test_only_approved(self):
        approved = [_make_approved("a1")]
        resp = _invoke_list([], approved)
        body = json.loads(resp["body"])

        assert len(body) == 1
        assert body[0]["proposalId"] == "a1"
        assert body[0]["status"] == "APPROVED"

    def test_cors_headers_present(self):
        resp = _invoke_list([], [])
        assert resp["headers"]["Access-Control-Allow-Origin"] == "*"
        assert resp["headers"]["Content-Type"] == "application/json"


class TestGetProposal:
    def test_returns_draft_when_found_in_draft_table(self):
        draft = _make_draft("d1")
        resp = _invoke_get("d1", [draft], [])
        body = json.loads(resp["body"])

        assert resp["statusCode"] == 200
        assert body["proposalId"] == "d1"

    def test_returns_approved_when_not_in_draft_table(self):
        approved = _make_approved("a1")
        resp = _invoke_get("a1", [], [approved])
        body = json.loads(resp["body"])

        assert resp["statusCode"] == 200
        assert body["proposalId"] == "a1"

    def test_returns_404_for_unknown_id(self):
        resp = _invoke_get("unknown-id", [], [])
        assert resp["statusCode"] == 404

    def test_404_body_contains_error_key(self):
        resp = _invoke_get("ghost", [], [])
        body = json.loads(resp["body"])
        assert "error" in body

    def test_draft_takes_priority_over_approved(self):
        """If same ID exists in both tables, draft is returned first."""
        draft = _make_draft("shared-id")
        approved = _make_approved("shared-id")
        resp = _invoke_get("shared-id", [draft], [approved])
        body = json.loads(resp["body"])

        assert resp["statusCode"] == 200
        assert body.get("status") == "PENDING"

    def test_cors_headers_present_on_404(self):
        resp = _invoke_get("nope", [], [])
        assert resp["headers"]["Access-Control-Allow-Origin"] == "*"


# ===========================================================================
# Property 12 — Task 2.2
# Validates: Requirements 6.1, 6.4
# ===========================================================================

proposal_id_st = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-"),
    min_size=1,
    max_size=36,
)


@st.composite
def unique_id_lists(draw, min_size=0, max_size=10):
    """Draw two disjoint lists of proposal IDs."""
    n = draw(st.integers(min_value=min_size, max_value=max_size))
    m = draw(st.integers(min_value=min_size, max_value=max_size))
    all_ids = draw(
        st.lists(proposal_id_st, min_size=n + m, max_size=n + m, unique=True)
    )
    return all_ids[:n], all_ids[n:]


@given(unique_id_lists())
@settings(max_examples=50)
def test_property_12_list_completeness(id_pair):
    """
    **Validates: Requirements 6.1, 6.4**

    Property 12: For any N draft records and M approved records,
    GET /proposals returns exactly N+M records.
    """
    draft_ids, approved_ids = id_pair
    drafts = [_make_draft(pid) for pid in draft_ids]
    approved = [_make_approved(pid) for pid in approved_ids]

    resp = _invoke_list(drafts, approved)
    body = json.loads(resp["body"])

    assert resp["statusCode"] == 200
    assert len(body) == len(drafts) + len(approved)

    returned_ids = {item["proposalId"] for item in body}
    expected_ids = set(draft_ids) | set(approved_ids)
    assert returned_ids == expected_ids


# ===========================================================================
# Property 13 — Task 2.3
# Validates: Requirements 6.2
# ===========================================================================

@st.composite
def existing_proposal_scenario(draw):
    """
    Draw a scenario: a proposal ID that exists in either draft or approved table,
    plus the full item stored there.
    """
    pid = draw(proposal_id_st)
    in_draft = draw(st.booleans())
    item = _make_draft(pid) if in_draft else _make_approved(pid)
    drafts = [item] if in_draft else []
    approved = [] if in_draft else [item]
    return pid, item, drafts, approved


@given(existing_proposal_scenario())
@settings(max_examples=50)
def test_property_13_full_record_returned(scenario):
    """
    **Validates: Requirements 6.2**

    Property 13: For any proposalId that exists in either table,
    GET /proposals/{id} returns the complete record.
    """
    pid, stored_item, drafts, approved = scenario

    resp = _invoke_get(pid, drafts, approved)
    body = json.loads(resp["body"])

    assert resp["statusCode"] == 200
    # Every field stored must be present in the response
    for key, value in stored_item.items():
        assert key in body, f"Field '{key}' missing from response"
        assert body[key] == value, f"Field '{key}' mismatch: {body[key]!r} != {value!r}"


# ===========================================================================
# Property 11 (GET path) — Task 2.4
# Validates: Requirements 6.3
# ===========================================================================

@st.composite
def unknown_id_scenario(draw):
    """
    Draw a proposalId that is guaranteed NOT to be in either table.
    """
    existing_ids = draw(
        st.lists(proposal_id_st, min_size=0, max_size=5, unique=True)
    )
    # Generate an ID that is not in existing_ids
    unknown_id = draw(
        proposal_id_st.filter(lambda x: x not in existing_ids)
    )
    drafts = [_make_draft(pid) for pid in existing_ids[: len(existing_ids) // 2]]
    approved = [_make_approved(pid) for pid in existing_ids[len(existing_ids) // 2 :]]
    return unknown_id, drafts, approved


@given(unknown_id_scenario())
@settings(max_examples=50)
def test_property_11_unknown_id_returns_404(scenario):
    """
    **Validates: Requirements 6.3**

    Property 11 (GET path): For any proposalId not in either table,
    GET /proposals/{id} returns HTTP 404.
    """
    unknown_id, drafts, approved = scenario

    resp = _invoke_get(unknown_id, drafts, approved)

    assert resp["statusCode"] == 404
    body = json.loads(resp["body"])
    assert "error" in body
