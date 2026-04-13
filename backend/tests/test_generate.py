"""
Unit and property-based tests for generate.py.

Covers:
  - Unit tests (Task 5.1): prompt construction, JSON parsing, section validation,
    error path (mock Gemini to throw → HTTP 502, no DynamoDB write)
  - Property 3 (Task 5.2): Successful generation produces a valid PENDING draft record
  - Property 4 (Task 5.3): Gemini errors never produce DynamoDB writes
  - Property 5 (Task 5.4): Generate Lambda never writes to Approved Table
  - Property 6 (Task 5.5): SOP content is always present in the Gemini system prompt
"""

import json
import sys
import os
import uuid
from datetime import datetime
from unittest.mock import MagicMock, patch, call

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

# ---------------------------------------------------------------------------
# Make backend/ importable without installing the package
# ---------------------------------------------------------------------------
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import generate as g

# ---------------------------------------------------------------------------
# Shared strategies
# ---------------------------------------------------------------------------

text_st = st.text(min_size=1, max_size=200)
section_name_st = st.sampled_from(g.REQUIRED_SECTIONS)
sop_content_st = st.text(min_size=1, max_size=500)

# A valid Gemini JSON response containing all required sections
def _make_gemini_json(extra_content: str = "content") -> str:
    sections = [
        {
            "sectionName": name,
            "content": f"{extra_content} for {name}",
            "rationale": f"rationale for {name}",
        }
        for name in g.REQUIRED_SECTIONS
    ]
    return json.dumps({"sections": sections})


def _make_mock_gemini_response(text: str) -> MagicMock:
    mock_resp = MagicMock()
    mock_resp.text = text
    return mock_resp


def _make_mock_s3(sop_texts: dict = None, image_data: dict = None):
    """
    Return a mock s3_client.
    sop_texts: {key: text_content}
    image_data: {key: bytes}
    """
    sop_texts = sop_texts or {}
    image_data = image_data or {}

    mock_s3 = MagicMock()

    def get_object(Bucket, Key):
        if Key in sop_texts:
            body = MagicMock()
            body.read.return_value = sop_texts[Key].encode("utf-8")
            return {"Body": body}
        if Key in image_data:
            body = MagicMock()
            body.read.return_value = image_data[Key]
            return {"Body": body}
        raise Exception(f"S3 key not found: {Key}")

    mock_s3.get_object.side_effect = get_object
    return mock_s3


def _make_mock_dynamodb(draft_store: list = None, approved_store: list = None,
                        approved_items: dict = None):
    """
    Return a mock boto3 dynamodb resource.
    draft_store / approved_store: mutable lists that capture put_item calls.
    approved_items: {proposalId: item} for get_item lookups on approved table.
    """
    if draft_store is None:
        draft_store = []
    if approved_store is None:
        approved_store = []
    if approved_items is None:
        approved_items = {}

    mock_db = MagicMock()
    draft_table = MagicMock()
    approved_table = MagicMock()

    draft_table.put_item.side_effect = lambda Item: draft_store.append(Item)

    approved_table.put_item.side_effect = lambda Item: approved_store.append(Item)

    def approved_get_item(Key):
        pid = Key["proposalId"]
        item = approved_items.get(pid)
        return {"Item": item} if item else {}

    approved_table.get_item.side_effect = approved_get_item

    def table_factory(name):
        if name == g.DRAFT_TABLE_NAME:
            return draft_table
        return approved_table

    mock_db.Table.side_effect = table_factory
    return mock_db, draft_store, approved_store


def _invoke_generate(body: dict, gemini_text: str = None, gemini_exc: Exception = None,
                     sop_texts: dict = None, image_data: dict = None,
                     approved_items: dict = None):
    """
    Invoke generate.handler with fully mocked dependencies.
    Returns (response, draft_store, approved_store).
    """
    draft_store = []
    approved_store = []
    mock_db, draft_store, approved_store = _make_mock_dynamodb(
        draft_store, approved_store, approved_items or {}
    )
    mock_s3 = _make_mock_s3(sop_texts or {}, image_data or {})

    mock_client_instance = MagicMock()
    if gemini_exc is not None:
        mock_client_instance.models.generate_content.side_effect = gemini_exc
    else:
        mock_client_instance.models.generate_content.return_value = (
            _make_mock_gemini_response(gemini_text or _make_gemini_json())
        )

    mock_client_cls = MagicMock(return_value=mock_client_instance)

    event = {"body": json.dumps(body)}

    with patch.object(g, "dynamodb", mock_db), \
         patch.object(g, "s3_client", mock_s3), \
         patch("generate.genai.Client", mock_client_cls):
        resp = g.handler(event)

    return resp, draft_store, approved_store, mock_client_instance


# ===========================================================================
# Unit Tests — Task 5.1
# ===========================================================================

class TestBuildSystemPrompt:
    def test_sop_content_appears_in_system_prompt(self):
        sop = "Always use formal language. Avoid jargon."
        prompt = g._build_system_prompt(sop)
        assert sop in prompt

    def test_system_prompt_contains_required_section_names(self):
        prompt = g._build_system_prompt("SOP text")
        for section in g.REQUIRED_SECTIONS:
            assert section in prompt

    def test_system_prompt_contains_json_schema_hint(self):
        prompt = g._build_system_prompt("SOP text")
        assert "sectionName" in prompt
        assert "content" in prompt
        assert "rationale" in prompt

    def test_empty_sop_still_produces_valid_prompt(self):
        prompt = g._build_system_prompt("")
        assert "proposal writer" in prompt.lower()


class TestBuildUserPrompt:
    def test_survey_notes_appear_in_user_prompt(self):
        notes = "Site visit on Monday. Roof needs repair."
        prompt = g._build_user_prompt(notes, [])
        assert notes in prompt

    def test_reference_sections_appear_in_user_prompt(self):
        sections = [{"sectionName": "Timeline", "content": "6 months"}]
        prompt = g._build_user_prompt("notes", sections)
        assert "Timeline" in prompt
        assert "6 months" in prompt

    def test_no_reference_sections_still_produces_prompt(self):
        prompt = g._build_user_prompt("notes", [])
        assert "notes" in prompt


class TestParseAndValidateResponse:
    def test_valid_response_returns_sections(self):
        raw = _make_gemini_json("test content")
        sections = g._parse_and_validate_response(raw)
        assert len(sections) == len(g.REQUIRED_SECTIONS)

    def test_malformed_json_raises_value_error(self):
        with pytest.raises(ValueError, match="malformed JSON"):
            g._parse_and_validate_response("not json at all")

    def test_missing_sections_key_raises_value_error(self):
        raw = json.dumps({"result": []})
        with pytest.raises(ValueError, match="missing 'sections'"):
            g._parse_and_validate_response(raw)

    def test_missing_one_required_section_raises_value_error(self):
        # Build response with all sections except the last one
        sections = [
            {"sectionName": name, "content": "c", "rationale": "r"}
            for name in g.REQUIRED_SECTIONS[:-1]  # drop last
        ]
        raw = json.dumps({"sections": sections})
        with pytest.raises(ValueError, match="missing required sections"):
            g._parse_and_validate_response(raw)

    def test_strips_markdown_code_fences(self):
        inner = _make_gemini_json()
        wrapped = f"```json\n{inner}\n```"
        sections = g._parse_and_validate_response(wrapped)
        assert len(sections) == len(g.REQUIRED_SECTIONS)

    def test_all_sections_have_required_fields(self):
        raw = _make_gemini_json()
        sections = g._parse_and_validate_response(raw)
        for sec in sections:
            assert "sectionName" in sec
            assert "content" in sec
            assert "rationale" in sec


class TestHandlerInputValidation:
    def test_missing_notes_and_files_returns_400(self):
        event = {"body": json.dumps({})}
        resp = g.handler(event)
        assert resp["statusCode"] == 400

    def test_whitespace_only_notes_and_no_files_returns_400(self):
        event = {"body": json.dumps({"surveyNotes": "   "})}
        resp = g.handler(event)
        assert resp["statusCode"] == 400

    def test_notes_only_passes_validation(self):
        resp, draft_store, _, _ = _invoke_generate(
            {"surveyNotes": "Some notes"},
            gemini_text=_make_gemini_json(),
        )
        assert resp["statusCode"] == 200

    def test_file_key_only_passes_validation(self):
        resp, draft_store, _, _ = _invoke_generate(
            {"photoKeys": ["photo/abc.jpg"]},
            gemini_text=_make_gemini_json(),
            image_data={"photo/abc.jpg": b"\xff\xd8\xff"},
        )
        assert resp["statusCode"] == 200


class TestHandlerSuccessPath:
    def test_success_returns_200(self):
        resp, _, _, _ = _invoke_generate({"surveyNotes": "notes"})
        assert resp["statusCode"] == 200

    def test_success_response_contains_proposal_id(self):
        resp, _, _, _ = _invoke_generate({"surveyNotes": "notes"})
        body = json.loads(resp["body"])
        assert "proposalId" in body
        # Should be a valid UUID
        uuid.UUID(body["proposalId"])

    def test_success_response_status_is_pending(self):
        resp, _, _, _ = _invoke_generate({"surveyNotes": "notes"})
        body = json.loads(resp["body"])
        assert body["status"] == "PENDING"

    def test_success_response_version_is_1(self):
        resp, _, _, _ = _invoke_generate({"surveyNotes": "notes"})
        body = json.loads(resp["body"])
        assert body["version"] == 1

    def test_success_response_created_at_is_iso8601(self):
        resp, _, _, _ = _invoke_generate({"surveyNotes": "notes"})
        body = json.loads(resp["body"])
        dt = datetime.fromisoformat(body["createdAt"].replace("Z", "+00:00"))
        assert dt is not None

    def test_success_writes_to_draft_table(self):
        resp, draft_store, _, _ = _invoke_generate({"surveyNotes": "notes"})
        assert len(draft_store) == 1

    def test_success_does_not_write_to_approved_table(self):
        resp, _, approved_store, _ = _invoke_generate({"surveyNotes": "notes"})
        assert len(approved_store) == 0

    def test_cors_headers_on_success(self):
        resp, _, _, _ = _invoke_generate({"surveyNotes": "notes"})
        assert resp["headers"]["Access-Control-Allow-Origin"] == "*"
        assert resp["headers"]["Content-Type"] == "application/json"


class TestHandlerErrorPath:
    def test_gemini_exception_returns_502(self):
        resp, _, _, _ = _invoke_generate(
            {"surveyNotes": "notes"},
            gemini_exc=RuntimeError("Gemini unavailable"),
        )
        assert resp["statusCode"] == 502

    def test_gemini_exception_no_draft_write(self):
        resp, draft_store, _, _ = _invoke_generate(
            {"surveyNotes": "notes"},
            gemini_exc=RuntimeError("Gemini unavailable"),
        )
        assert len(draft_store) == 0

    def test_gemini_exception_no_approved_write(self):
        resp, _, approved_store, _ = _invoke_generate(
            {"surveyNotes": "notes"},
            gemini_exc=RuntimeError("Gemini unavailable"),
        )
        assert len(approved_store) == 0

    def test_malformed_json_returns_502(self):
        resp, draft_store, _, _ = _invoke_generate(
            {"surveyNotes": "notes"},
            gemini_text="this is not json",
        )
        assert resp["statusCode"] == 502
        assert len(draft_store) == 0

    def test_missing_required_section_returns_502(self):
        # Response with only 5 of 6 required sections
        sections = [
            {"sectionName": name, "content": "c", "rationale": "r"}
            for name in g.REQUIRED_SECTIONS[:-1]
        ]
        partial_json = json.dumps({"sections": sections})
        resp, draft_store, _, _ = _invoke_generate(
            {"surveyNotes": "notes"},
            gemini_text=partial_json,
        )
        assert resp["statusCode"] == 502
        assert len(draft_store) == 0

    def test_502_body_contains_error_key(self):
        resp, _, _, _ = _invoke_generate(
            {"surveyNotes": "notes"},
            gemini_exc=RuntimeError("boom"),
        )
        body = json.loads(resp["body"])
        assert "error" in body

    def test_cors_headers_on_502(self):
        resp, _, _, _ = _invoke_generate(
            {"surveyNotes": "notes"},
            gemini_exc=RuntimeError("boom"),
        )
        assert resp["headers"]["Access-Control-Allow-Origin"] == "*"

    def test_s3_error_returns_502_no_db_write(self):
        """S3 failure during SOP fetch should return 502 and not write to DynamoDB."""
        draft_store = []
        approved_store = []
        mock_db, draft_store, approved_store = _make_mock_dynamodb(draft_store, approved_store)

        mock_s3 = MagicMock()
        mock_s3.get_object.side_effect = Exception("S3 access denied")

        mock_client_cls = MagicMock()

        event = {"body": json.dumps({"surveyNotes": "notes", "sopKeys": ["sop/doc.pdf"]})}

        with patch.object(g, "dynamodb", mock_db), \
             patch.object(g, "s3_client", mock_s3), \
             patch("generate.genai.Client", mock_client_cls):
            resp = g.handler(event)

        assert resp["statusCode"] == 502
        assert len(draft_store) == 0
        assert len(approved_store) == 0


# ===========================================================================
# Property 3 — Task 5.2
# Validates: Requirements 3.2, 3.3, 3.6
# ===========================================================================

@st.composite
def valid_gemini_response_st(draw):
    """Generate a valid Gemini JSON response with all required sections."""
    sections = []
    for name in g.REQUIRED_SECTIONS:
        content = draw(st.text(min_size=1, max_size=200))
        rationale = draw(st.text(min_size=1, max_size=200))
        sections.append({"sectionName": name, "content": content, "rationale": rationale})
    return json.dumps({"sections": sections})


@given(
    survey_notes=st.text(min_size=1, max_size=300),
    gemini_json=valid_gemini_response_st(),
)
@settings(max_examples=50)
def test_property_3_successful_generation_produces_pending_draft(survey_notes, gemini_json):
    """
    **Validates: Requirements 3.2, 3.3, 3.6**

    Property 3: For any valid Gemini JSON response, generate.py SHALL produce a
    record in proposals_draft with status=PENDING, a UUID proposalId, a valid
    ISO 8601 createdAt, version=1, and each section containing sectionName,
    content, and rationale. The same record SHALL be returned in the HTTP 200 body.
    """
    resp, draft_store, _, _ = _invoke_generate(
        {"surveyNotes": survey_notes},
        gemini_text=gemini_json,
    )

    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])

    # Status, version
    assert body["status"] == "PENDING"
    assert body["version"] == 1

    # Valid UUID proposalId
    uuid.UUID(body["proposalId"])

    # Valid ISO 8601 createdAt
    datetime.fromisoformat(body["createdAt"].replace("Z", "+00:00"))

    # Sections present with required fields
    sections = body["aiGeneratedSections"]
    assert isinstance(sections, list)
    assert len(sections) == len(g.REQUIRED_SECTIONS)
    for sec in sections:
        assert "sectionName" in sec
        assert "content" in sec
        assert "rationale" in sec

    # Exactly one write to draft table
    assert len(draft_store) == 1
    saved = draft_store[0]

    # Response body matches saved record
    assert body["proposalId"] == saved["proposalId"]
    assert body["status"] == saved["status"]
    assert body["version"] == saved["version"]
    assert body["createdAt"] == saved["createdAt"]
    assert body["aiGeneratedSections"] == saved["aiGeneratedSections"]


# ===========================================================================
# Property 4 — Task 5.3
# Validates: Requirements 3.5, 9.3
# ===========================================================================

@st.composite
def gemini_error_scenario_st(draw):
    """
    Generate an error scenario: either a Gemini exception, malformed JSON,
    or a JSON response missing one or more required sections.
    """
    error_type = draw(st.sampled_from(["exception", "malformed_json", "missing_section"]))

    if error_type == "exception":
        msg = draw(st.text(min_size=1, max_size=100))
        return {"exc": RuntimeError(msg), "text": None}

    if error_type == "malformed_json":
        bad_text = draw(st.text(min_size=1, max_size=100).filter(
            lambda t: not t.strip().startswith("{")
        ))
        return {"exc": None, "text": bad_text}

    # missing_section: drop 1–6 required sections
    n_drop = draw(st.integers(min_value=1, max_value=len(g.REQUIRED_SECTIONS)))
    kept = g.REQUIRED_SECTIONS[:-n_drop]
    sections = [{"sectionName": n, "content": "c", "rationale": "r"} for n in kept]
    return {"exc": None, "text": json.dumps({"sections": sections})}


@given(
    survey_notes=st.text(min_size=1, max_size=200),
    error_scenario=gemini_error_scenario_st(),
)
@settings(max_examples=50)
def test_property_4_gemini_errors_never_produce_db_writes(survey_notes, error_scenario):
    """
    **Validates: Requirements 3.5, 9.3**

    Property 4: For any error condition from Gemini (exception, malformed JSON,
    missing required sections), generate.py SHALL return HTTP 502 and make zero
    write calls to either proposals_draft or proposals_approved.
    """
    resp, draft_store, approved_store, _ = _invoke_generate(
        {"surveyNotes": survey_notes},
        gemini_text=error_scenario["text"],
        gemini_exc=error_scenario["exc"],
    )

    assert resp["statusCode"] == 502
    assert len(draft_store) == 0
    assert len(approved_store) == 0

    body = json.loads(resp["body"])
    assert "error" in body


# ===========================================================================
# Property 5 — Task 5.4
# Validates: Requirements 3.4, 5.4
# ===========================================================================

@given(
    survey_notes=st.text(min_size=1, max_size=200),
    gemini_json=valid_gemini_response_st(),
)
@settings(max_examples=50)
def test_property_5_generate_never_writes_to_approved_table(survey_notes, gemini_json):
    """
    **Validates: Requirements 3.4, 5.4**

    Property 5: For any input to generate.py, no write operation SHALL be made
    against the proposals_approved DynamoDB table.
    """
    resp, _, approved_store, _ = _invoke_generate(
        {"surveyNotes": survey_notes},
        gemini_text=gemini_json,
    )

    # Whether success or failure, approved table must never be written
    assert len(approved_store) == 0


@given(
    survey_notes=st.text(min_size=1, max_size=200),
    error_scenario=gemini_error_scenario_st(),
)
@settings(max_examples=30)
def test_property_5_generate_never_writes_to_approved_table_on_error(survey_notes, error_scenario):
    """
    **Validates: Requirements 3.4, 5.4**

    Property 5 (error path): Even on Gemini errors, no write to proposals_approved.
    """
    resp, _, approved_store, _ = _invoke_generate(
        {"surveyNotes": survey_notes},
        gemini_text=error_scenario["text"],
        gemini_exc=error_scenario["exc"],
    )

    assert len(approved_store) == 0


# ===========================================================================
# Property 6 — Task 5.5
# Validates: Requirements 8.4
# ===========================================================================

@given(
    sop_content=sop_content_st,
    survey_notes=st.text(min_size=1, max_size=200),
    gemini_json=valid_gemini_response_st(),
)
@settings(max_examples=50)
def test_property_6_sop_content_in_system_prompt(sop_content, survey_notes, gemini_json):
    """
    **Validates: Requirements 8.4**

    Property 6: For any SOP document content extracted from S3, that content
    SHALL appear verbatim in the system prompt string passed to the Gemini API call.
    """
    sop_key = "sop/guidelines.txt"

    draft_store = []
    approved_store = []
    mock_db, draft_store, approved_store = _make_mock_dynamodb(draft_store, approved_store)
    mock_s3 = _make_mock_s3(sop_texts={sop_key: sop_content})

    captured_system_prompt = []

    mock_client_instance = MagicMock()
    mock_client_instance.models.generate_content.return_value = (
        _make_mock_gemini_response(gemini_json)
    )

    # Intercept the generate_content call to capture the system_instruction
    original_side_effect = mock_client_instance.models.generate_content.side_effect

    def capture_call(**kwargs):
        config = kwargs.get("config")
        if config is not None:
            captured_system_prompt.append(config.system_instruction)
        return _make_mock_gemini_response(gemini_json)

    mock_client_instance.models.generate_content.side_effect = capture_call

    mock_client_cls = MagicMock(return_value=mock_client_instance)

    event = {"body": json.dumps({
        "surveyNotes": survey_notes,
        "sopKeys": [sop_key],
    })}

    with patch.object(g, "dynamodb", mock_db), \
         patch.object(g, "s3_client", mock_s3), \
         patch("generate.genai.Client", mock_client_cls):
        resp = g.handler(event)

    assert resp["statusCode"] == 200, f"Expected 200, got {resp['statusCode']}: {resp['body']}"

    # The system prompt must have been captured
    assert len(captured_system_prompt) == 1, "generate_content was not called"
    system_prompt = captured_system_prompt[0]

    # SOP content must appear verbatim in the system prompt
    assert sop_content in system_prompt, (
        f"SOP content not found in system prompt.\n"
        f"SOP: {sop_content!r}\n"
        f"Prompt: {system_prompt!r}"
    )
