"""
Unit and property-based tests for proposals.py approve path.

Covers:
  - Unit tests (Task 3.1): editsMade diff logic, successful approve, 404 on missing draft
  - Property 9  (Task 3.2): approve round-trip — saved record matches returned record
  - Property 10 (Task 3.3): editsMade accurately captures section diffs
  - Property 11 POST path (Task 3.4): unknown proposalId always returns 404 on POST /approve
"""

import json
import sys
import os
from unittest.mock import MagicMock, patch, call

import pytest
from hypothesis import given, settings
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Make backend/ importable without installing the package
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import proposals as p

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_draft(proposal_id: str, ai_sections: list = None, version: int = 1) -> dict:
    return {
        "proposalId": proposal_id,
        "status": "PENDING",
        "createdAt": "2024-01-01T00:00:00Z",
        "surveyNotes": "some notes",
        "aiGeneratedSections": ai_sections or [],
        "version": version,
    }


def _make_section(name: str, content: str) -> dict:
    return {"sectionName": name, "content": content}


def _build_mock_dynamodb(draft_items: list, approved_store: list = None):
    """
    Return a mock boto3 dynamodb resource.
    approved_store is a mutable list that captures put_item calls.
    """
    if approved_store is None:
        approved_store = []

    mock_dynamodb = MagicMock()
    draft_table = MagicMock()
    approved_table = MagicMock()

    def draft_get_item(Key):
        pid = Key["proposalId"]
        match = next((i for i in draft_items if i["proposalId"] == pid), None)
        return {"Item": match} if match else {}

    draft_table.get_item.side_effect = draft_get_item

    def approved_put_item(Item):
        approved_store.append(Item)

    approved_table.put_item.side_effect = approved_put_item

    def table_factory(name):
        if name == p.DRAFT_TABLE_NAME:
            return draft_table
        return approved_table

    mock_dynamodb.Table.side_effect = table_factory
    return mock_dynamodb, approved_store


def _invoke_approve(body: dict, draft_items: list):
    """Call handle_approve with mocked DynamoDB; returns (response, approved_store)."""
    mock_db, approved_store = _build_mock_dynamodb(draft_items)
    event = {"body": json.dumps(body)}
    with patch.object(p, "dynamodb", mock_db):
        resp = p.handle_approve(event)
    return resp, approved_store


# ===========================================================================
# Unit Tests — Task 3.1
# ===========================================================================

class TestComputeEditsMade:
    """Tests for the _compute_edits_made helper directly."""

    def test_changed_section_appears_in_edits(self):
        ai = [_make_section("Executive Summary", "AI content")]
        final = [_make_section("Executive Summary", "Human edited content")]
        edits = p._compute_edits_made(ai, final)
        assert "Executive Summary" in edits
        assert edits["Executive Summary"]["original"] == "AI content"
        assert edits["Executive Summary"]["final"] == "Human edited content"

    def test_unchanged_section_not_in_edits(self):
        ai = [_make_section("Scope of Work", "Same content")]
        final = [_make_section("Scope of Work", "Same content")]
        edits = p._compute_edits_made(ai, final)
        assert "Scope of Work" not in edits

    def test_mixed_sections_only_changed_appear(self):
        ai = [
            _make_section("Executive Summary", "AI summary"),
            _make_section("Timeline", "6 months"),
            _make_section("Budget Estimate", "100k"),
        ]
        final = [
            _make_section("Executive Summary", "Human summary"),
            _make_section("Timeline", "6 months"),  # unchanged
            _make_section("Budget Estimate", "120k"),
        ]
        edits = p._compute_edits_made(ai, final)
        assert "Executive Summary" in edits
        assert "Budget Estimate" in edits
        assert "Timeline" not in edits

    def test_empty_sections_produce_no_edits(self):
        edits = p._compute_edits_made([], [])
        assert edits == {}

    def test_new_section_not_in_ai_treated_as_changed(self):
        """A section in final that wasn't in AI is treated as changed (original='')."""
        ai = []
        final = [_make_section("New Section", "Some content")]
        edits = p._compute_edits_made(ai, final)
        assert "New Section" in edits
        assert edits["New Section"]["original"] == ""
        assert edits["New Section"]["final"] == "Some content"


class TestHandleApprove:
    def test_successful_approve_returns_200(self):
        draft = _make_draft("pid-1", ai_sections=[_make_section("Scope", "AI scope")])
        final_sections = [_make_section("Scope", "Human scope")]
        resp, _ = _invoke_approve(
            {"proposalId": "pid-1", "finalSections": final_sections, "approvedBy": "user@example.com"},
            [draft],
        )
        assert resp["statusCode"] == 200

    def test_successful_approve_writes_to_approved_table(self):
        draft = _make_draft("pid-2", ai_sections=[])
        resp, approved_store = _invoke_approve(
            {"proposalId": "pid-2", "finalSections": [], "approvedBy": "user@example.com"},
            [draft],
        )
        assert len(approved_store) == 1
        assert approved_store[0]["proposalId"] == "pid-2"

    def test_approve_record_contains_required_fields(self):
        draft = _make_draft("pid-3", ai_sections=[], version=2)
        resp, approved_store = _invoke_approve(
            {"proposalId": "pid-3", "finalSections": [], "approvedBy": "alice"},
            [draft],
        )
        body = json.loads(resp["body"])
        for field in ("proposalId", "finalSections", "approvedBy", "approvedAt", "editsMade", "version"):
            assert field in body, f"Missing field: {field}"

    def test_approve_copies_version_from_draft(self):
        draft = _make_draft("pid-4", version=3)
        resp, _ = _invoke_approve(
            {"proposalId": "pid-4", "finalSections": [], "approvedBy": "bob"},
            [draft],
        )
        body = json.loads(resp["body"])
        assert body["version"] == 3

    def test_approve_approved_at_is_iso8601(self):
        from datetime import datetime
        draft = _make_draft("pid-5")
        resp, _ = _invoke_approve(
            {"proposalId": "pid-5", "finalSections": [], "approvedBy": "carol"},
            [draft],
        )
        body = json.loads(resp["body"])
        # Should parse without error
        dt = datetime.fromisoformat(body["approvedAt"].replace("Z", "+00:00"))
        assert dt is not None

    def test_missing_draft_returns_404(self):
        resp, approved_store = _invoke_approve(
            {"proposalId": "nonexistent", "finalSections": [], "approvedBy": "user"},
            [],  # empty draft table
        )
        assert resp["statusCode"] == 404
        assert len(approved_store) == 0

    def test_404_body_contains_error_key(self):
        resp, _ = _invoke_approve(
            {"proposalId": "ghost-id", "finalSections": [], "approvedBy": "user"},
            [],
        )
        body = json.loads(resp["body"])
        assert "error" in body

    def test_cors_headers_on_200(self):
        draft = _make_draft("pid-6")
        resp, _ = _invoke_approve(
            {"proposalId": "pid-6", "finalSections": [], "approvedBy": "user"},
            [draft],
        )
        assert resp["headers"]["Access-Control-Allow-Origin"] == "*"
        assert resp["headers"]["Content-Type"] == "application/json"

    def test_cors_headers_on_404(self):
        resp, _ = _invoke_approve(
            {"proposalId": "missing", "finalSections": [], "approvedBy": "user"},
            [],
        )
        assert resp["headers"]["Access-Control-Allow-Origin"] == "*"

    def test_edits_made_populated_correctly(self):
        ai_sections = [
            _make_section("Executive Summary", "AI text"),
            _make_section("Timeline", "3 months"),
        ]
        final_sections = [
            _make_section("Executive Summary", "Human text"),
            _make_section("Timeline", "3 months"),  # unchanged
        ]
        draft = _make_draft("pid-7", ai_sections=ai_sections)
        resp, _ = _invoke_approve(
            {"proposalId": "pid-7", "finalSections": final_sections, "approvedBy": "user"},
            [draft],
        )
        body = json.loads(resp["body"])
        edits = body["editsMade"]
        assert "Executive Summary" in edits
        assert "Timeline" not in edits


# ===========================================================================
# Property 9 — Task 3.2
# Validates: Requirements 5.2, 5.6
# ===========================================================================

section_name_st = st.sampled_from([
    "Executive Summary", "Scope of Work", "Timeline",
    "Budget Estimate", "Methodology", "Assumptions & Exclusions",
])

section_content_st = st.text(min_size=0, max_size=200)

section_st = st.fixed_dictionaries({
    "sectionName": section_name_st,
    "content": section_content_st,
})

unique_sections_st = st.lists(
    st.fixed_dictionaries({
        "sectionName": section_name_st,
        "content": section_content_st,
    }),
    min_size=0,
    max_size=6,
    unique_by=lambda s: s["sectionName"],
)

proposal_id_st = st.text(
    alphabet=st.characters(whitelist_categories=("Lu", "Ll", "Nd"), whitelist_characters="-"),
    min_size=1,
    max_size=36,
)

approved_by_st = st.text(min_size=1, max_size=50)


@given(
    proposal_id=proposal_id_st,
    final_sections=unique_sections_st,
    approved_by=approved_by_st,
    version=st.integers(min_value=1, max_value=10),
)
@settings(max_examples=50)
def test_property_9_approve_round_trip(proposal_id, final_sections, approved_by, version):
    """
    **Validates: Requirements 5.2, 5.6**

    Property 9: For any valid approve request where the draft exists,
    the HTTP 200 response body SHALL match the record written to proposals_approved exactly.
    """
    draft = _make_draft(proposal_id, ai_sections=[], version=version)
    mock_db, approved_store = _build_mock_dynamodb([draft])

    event = {"body": json.dumps({
        "proposalId": proposal_id,
        "finalSections": final_sections,
        "approvedBy": approved_by,
    })}

    with patch.object(p, "dynamodb", mock_db):
        resp = p.handle_approve(event)

    assert resp["statusCode"] == 200
    returned = json.loads(resp["body"])

    # Exactly one record written
    assert len(approved_store) == 1
    saved = approved_store[0]

    # Response body must match saved record on all key fields
    assert returned["proposalId"] == saved["proposalId"]
    assert returned["finalSections"] == saved["finalSections"]
    assert returned["approvedBy"] == saved["approvedBy"]
    assert returned["approvedAt"] == saved["approvedAt"]
    assert returned["editsMade"] == saved["editsMade"]
    assert returned["version"] == saved["version"]


# ===========================================================================
# Property 10 — Task 3.3
# Validates: Requirements 5.3
# ===========================================================================

@st.composite
def ai_and_final_sections_st(draw):
    """
    Draw a set of section names, then for each section independently decide
    whether the final content matches the AI content or differs.
    """
    names = draw(st.lists(section_name_st, min_size=0, max_size=6, unique=True))
    ai_sections = []
    final_sections = []
    changed_names = set()

    for name in names:
        ai_content = draw(st.text(min_size=1, max_size=100))
        should_change = draw(st.booleans())
        if should_change:
            # Ensure final content is different
            final_content = draw(st.text(min_size=1, max_size=100).filter(lambda c: c != ai_content))
            changed_names.add(name)
        else:
            final_content = ai_content

        ai_sections.append({"sectionName": name, "content": ai_content})
        final_sections.append({"sectionName": name, "content": final_content})

    return ai_sections, final_sections, changed_names


@given(ai_and_final_sections_st())
@settings(max_examples=50)
def test_property_10_edits_made_accuracy(scenario):
    """
    **Validates: Requirements 5.3**

    Property 10: editsMade contains exactly the sections where content differs,
    with correct original and final values. Unchanged sections must not appear.
    """
    ai_sections, final_sections, changed_names = scenario

    edits = p._compute_edits_made(ai_sections, final_sections)

    # Only changed sections appear
    assert set(edits.keys()) == changed_names

    # For each changed section, values are correct
    ai_by_name = {s["sectionName"]: s["content"] for s in ai_sections}
    final_by_name = {s["sectionName"]: s["content"] for s in final_sections}

    for name in changed_names:
        assert edits[name]["original"] == ai_by_name[name]
        assert edits[name]["final"] == final_by_name[name]
        assert edits[name]["original"] != edits[name]["final"]


# ===========================================================================
# Property 11 (POST path) — Task 3.4
# Validates: Requirements 5.5
# ===========================================================================

@st.composite
def unknown_proposal_id_scenario(draw):
    """
    Draw a set of existing draft IDs and a proposalId guaranteed not to be among them.
    """
    existing_ids = draw(
        st.lists(proposal_id_st, min_size=0, max_size=5, unique=True)
    )
    unknown_id = draw(proposal_id_st.filter(lambda x: x not in existing_ids))
    drafts = [_make_draft(pid) for pid in existing_ids]
    return unknown_id, drafts


@given(unknown_proposal_id_scenario())
@settings(max_examples=50)
def test_property_11_post_unknown_id_returns_404(scenario):
    """
    **Validates: Requirements 5.5**

    Property 11 (POST path): For any proposalId not in proposals_draft,
    POST /approve returns HTTP 404 and makes no write to proposals_approved.
    """
    unknown_id, drafts = scenario
    mock_db, approved_store = _build_mock_dynamodb(drafts)

    event = {"body": json.dumps({
        "proposalId": unknown_id,
        "finalSections": [],
        "approvedBy": "user",
    })}

    with patch.object(p, "dynamodb", mock_db):
        resp = p.handle_approve(event)

    assert resp["statusCode"] == 404
    assert len(approved_store) == 0

    body = json.loads(resp["body"])
    assert "error" in body
