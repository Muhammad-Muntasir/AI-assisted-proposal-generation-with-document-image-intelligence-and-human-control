"""
handler.py
----------
Unified AWS Lambda handler for all AI proposal endpoints.
Consolidates generate.py and proposals.py into a single function to reduce costs.

Routes:
  - POST /generate       → Generate AI proposal draft
  - POST /upload-url     → Generate pre-signed S3 URL for file uploads
  - POST /approve        → Approve a draft proposal
  - GET  /proposals      → List all proposals
  - GET  /proposals/{id} → Get a single proposal by ID
"""

import json
import os
import uuid
import time
import re
from datetime import datetime, timezone
from decimal import Decimal

import boto3
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# Config — read from Lambda environment variables
# ---------------------------------------------------------------------------

DRAFT_TABLE_NAME     = os.environ.get("DRAFT_TABLE_NAME", "proposals_draft")
APPROVED_TABLE_NAME  = os.environ.get("APPROVED_TABLE_NAME", "proposals_approved")
UPLOADS_BUCKET_NAME  = os.environ.get("UPLOADS_BUCKET_NAME", "uploads-bucket")
GEMINI_API_KEY_PARAM = os.environ.get("GEMINI_API_KEY_PARAM", "/ai-proposal/gemini-api-key")

# AWS clients
dynamodb   = boto3.resource("dynamodb")
s3_client  = boto3.client("s3")
ssm_client = boto3.client("ssm")

# CORS headers
CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
}

# Required proposal sections
REQUIRED_SECTIONS = [
    "Executive Summary",
    "Scope of Work",
    "Timeline",
    "Budget Estimate",
    "Methodology",
    "Assumptions & Exclusions",
]

# System prompt template
SYSTEM_PROMPT_TEMPLATE = """\
You are a professional proposal writer.
You follow the company's writing guidelines and standards exactly as specified in the SOP documents provided.

Your task is to generate a structured project proposal in JSON format.

COMPANY WRITING GUIDELINES (SOP):
{sop_content}

OUTPUT FORMAT — you MUST return valid JSON matching this schema exactly:
{{
  "sections": [
    {{
      "sectionName": "<section name>",
      "content": "<full section content>",
      "rationale": "<why this content was chosen based on the inputs>"
    }}
  ]
}}

Required sections (you MUST include all of these):
- Executive Summary
- Scope of Work
- Timeline
- Budget Estimate
- Methodology
- Assumptions & Exclusions

Do not include any text outside the JSON object.\
"""


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

class DecimalEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle DynamoDB Decimal types."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            return int(obj) if obj % 1 == 0 else float(obj)
        return super().default(obj)


def _response(status_code: int, body: object) -> dict:
    """Build a standard API Gateway response with CORS headers."""
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body, cls=DecimalEncoder),
    }


def _get_gemini_api_key() -> str:
    """Fetch the Gemini API key from AWS SSM Parameter Store."""
    resp = ssm_client.get_parameter(Name=GEMINI_API_KEY_PARAM, WithDecryption=True)
    return resp["Parameter"]["Value"]


def _build_system_prompt(sop_content: str) -> str:
    """Inject SOP document content into the system prompt template."""
    return SYSTEM_PROMPT_TEMPLATE.format(sop_content=sop_content)


def _build_user_prompt(survey_notes: str, reference_sections: list) -> str:
    """Build the user-facing prompt with survey notes and optional reference proposal."""
    lines = ["Generate a project proposal based on the following inputs:"]
    lines.append("\nSURVEY NOTES:")
    lines.append(survey_notes or "(none provided)")

    if reference_sections:
        lines.append("\nREFERENCE PROPOSAL (for style and structure guidance):")
        for sec in reference_sections:
            lines.append(f"  [{sec.get('sectionName', '')}]: {sec.get('content', '')}")

    return "\n".join(lines)


def _fetch_sop_content(sop_keys: list) -> str:
    """Download SOP documents from S3 and return their text content combined."""
    parts = []
    for key in sop_keys:
        obj = s3_client.get_object(Bucket=UPLOADS_BUCKET_NAME, Key=key)
        text = obj["Body"].read().decode("utf-8", errors="replace")
        parts.append(text)
    return "\n\n".join(parts)


def _fetch_image_bytes(photo_keys: list) -> list:
    """Download site photos from S3 and return as raw bytes list."""
    images = []
    for key in photo_keys:
        obj = s3_client.get_object(Bucket=UPLOADS_BUCKET_NAME, Key=key)
        images.append(obj["Body"].read())
    return images


def _fetch_reference_sections(reference_proposal_id: str) -> list:
    """Load an approved proposal's sections from DynamoDB to use as reference."""
    table = dynamodb.Table(APPROVED_TABLE_NAME)
    resp = table.get_item(Key={"proposalId": reference_proposal_id})
    item = resp.get("Item")
    if not item:
        return []
    return item.get("finalSections", [])


def _parse_and_validate_response(raw_text: str) -> list:
    """Parse the AI response JSON and check all required sections are present."""
    text = raw_text.strip()

    # Remove markdown code fences if present
    if text.startswith("```"):
        lines = text.splitlines()
        text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"Gemini returned malformed JSON: {exc}") from exc

    sections = data.get("sections")
    if not isinstance(sections, list):
        raise ValueError("Gemini response missing 'sections' array")

    # Check all required sections are present
    present = {s.get("sectionName") for s in sections}
    missing = [name for name in REQUIRED_SECTIONS if name not in present]
    if missing:
        raise ValueError(f"Gemini response missing required sections: {missing}")

    return sections


def _compute_edits_made(ai_sections: list, final_sections: list) -> dict:
    """Compare AI-generated sections vs human-edited final sections."""
    ai_by_name = {s["sectionName"]: s.get("content", "") for s in ai_sections}
    edits_made = {}
    for section in final_sections:
        name          = section["sectionName"]
        final_content = section.get("content", "")
        ai_content    = ai_by_name.get(name, "")
        if final_content != ai_content:
            edits_made[name] = {"original": ai_content, "final": final_content}
    return edits_made


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------

def handle_generate(event: dict) -> dict:
    """POST /generate — Generate AI proposal draft."""
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        body = {}

    survey_notes          = body.get("surveyNotes", "").strip()
    photo_keys            = body.get("photoKeys") or []
    document_keys         = body.get("documentKeys") or []
    sop_keys              = body.get("sopKeys") or []
    reference_proposal_id = body.get("referenceProposalId")

    has_notes = bool(survey_notes)
    has_files = bool(photo_keys or document_keys or sop_keys)
    if not has_notes and not has_files:
        return _response(400, {"error": "Request must include surveyNotes or at least one file key"})

    try:
        # Load SOP guidelines from S3
        sop_content = _fetch_sop_content(sop_keys) if sop_keys else "(No SOP documents provided)"

        # Load reference proposal sections
        reference_sections = []
        if reference_proposal_id:
            reference_sections = _fetch_reference_sections(reference_proposal_id)

        # Build AI prompts
        system_prompt    = _build_system_prompt(sop_content)
        user_prompt_text = _build_user_prompt(survey_notes, reference_sections)

        # Download site photos
        image_bytes_list = _fetch_image_bytes(photo_keys) if photo_keys else []

        # Build multimodal content
        parts = [types.Part.from_text(text=user_prompt_text)]
        for image_bytes in image_bytes_list:
            parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))

        # Call Gemini AI with retry logic
        client   = genai.Client(api_key=_get_gemini_api_key())
        last_exc = None
        for attempt in range(4):
            try:
                response = client.models.generate_content(
                    model="gemini-2.0-flash",
                    contents=[types.Content(role="user", parts=parts)],
                    config=types.GenerateContentConfig(system_instruction=system_prompt),
                )
                break
            except Exception as exc:
                last_exc = exc
                err_str = str(exc)
                is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
                is_overloaded = "503" in err_str or "UNAVAILABLE" in err_str
                if attempt < 3 and (is_rate_limit or is_overloaded):
                    match = re.search(r"retryDelay['\"]?\s*[:\s]+['\"]?(\d+)", err_str)
                    wait = int(match.group(1)) if match else (45 if is_rate_limit else 5)
                    wait = min(wait, 50)
                    time.sleep(wait)
                else:
                    break
        else:
            pass
        if last_exc and 'response' not in dir():
            raise last_exc

        # Parse and validate AI response
        sections = _parse_and_validate_response(response.text)

        # Build draft record
        proposal_id = str(uuid.uuid4())
        created_at  = datetime.now(timezone.utc).isoformat()

        record = {
            "proposalId":          proposal_id,
            "surveyNotes":         survey_notes,
            "aiGeneratedSections": sections,
            "status":              "PENDING",
            "createdAt":           created_at,
            "version":             1,
        }

        # Save draft to DynamoDB
        draft_table = dynamodb.Table(DRAFT_TABLE_NAME)
        draft_table.put_item(Item=record)

        return _response(200, record)

    except Exception as exc:
        return _response(502, {"error": str(exc)})


def handle_upload_url(event: dict) -> dict:
    """POST /upload-url — Generate pre-signed S3 URL for file upload."""
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        body = {}

    file_name = body.get("fileName", "upload")
    file_type = body.get("fileType", "application/octet-stream")

    s3_key = f"uploads/{uuid.uuid4()}/{file_name}"

    presigned_url = s3_client.generate_presigned_url(
        "put_object",
        Params={
            "Bucket": UPLOADS_BUCKET_NAME,
            "Key": s3_key,
            "ContentType": file_type,
        },
        ExpiresIn=300,
    )

    return _response(200, {"uploadUrl": presigned_url, "s3Key": s3_key})


def handle_approve(event: dict) -> dict:
    """POST /approve — Approve a draft proposal."""
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        body = {}

    proposal_id    = body.get("proposalId")
    final_sections = body.get("finalSections", [])
    approved_by    = body.get("approvedBy", "")

    if not proposal_id:
        return _response(400, {"error": "proposalId is required"})

    # Load draft
    draft_table = dynamodb.Table(DRAFT_TABLE_NAME)
    draft_resp  = draft_table.get_item(Key={"proposalId": proposal_id})
    draft       = draft_resp.get("Item")

    if not draft:
        return _response(404, {"error": f"Proposal '{proposal_id}' not found in draft table"})

    # Calculate edits
    ai_sections = draft.get("aiGeneratedSections", [])
    edits_made  = _compute_edits_made(ai_sections, final_sections)

    # Build approved record
    approved_at = datetime.now(timezone.utc).isoformat()
    record = {
        "proposalId":    proposal_id,
        "finalSections": final_sections,
        "approvedBy":    approved_by,
        "approvedAt":    approved_at,
        "editsMade":     edits_made,
        "version":       draft.get("version", 1),
    }

    # Save to approved table
    approved_table = dynamodb.Table(APPROVED_TABLE_NAME)
    approved_table.put_item(Item=record)

    # Update draft status
    draft_table.update_item(
        Key={"proposalId": proposal_id},
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "APPROVED"},
    )

    return _response(200, record)


def handle_list_proposals() -> dict:
    """GET /proposals — List all proposals."""
    draft_table    = dynamodb.Table(DRAFT_TABLE_NAME)
    approved_table = dynamodb.Table(APPROVED_TABLE_NAME)

    # Scan draft table
    draft_result = draft_table.scan(
        ProjectionExpression="proposalId, #s, createdAt",
        ExpressionAttributeNames={"#s": "status"},
    )
    drafts = [
        {
            "proposalId": item["proposalId"],
            "status":     item.get("status", "PENDING"),
            "createdAt":  item.get("createdAt"),
        }
        for item in draft_result.get("Items", [])
    ]

    # Scan approved table
    approved_result = approved_table.scan(
        ProjectionExpression="proposalId, approvedAt",
    )
    approved = [
        {
            "proposalId": item["proposalId"],
            "status":     "APPROVED",
            "approvedAt": item.get("approvedAt"),
        }
        for item in approved_result.get("Items", [])
    ]

    return _response(200, drafts + approved)


def handle_get_proposal(proposal_id: str) -> dict:
    """GET /proposals/{id} — Get a single proposal by ID."""
    draft_table    = dynamodb.Table(DRAFT_TABLE_NAME)
    approved_table = dynamodb.Table(APPROVED_TABLE_NAME)

    # Check draft table first
    draft_resp = draft_table.get_item(Key={"proposalId": proposal_id})
    item       = draft_resp.get("Item")

    # If not in drafts, check approved table
    if not item:
        approved_resp = approved_table.get_item(Key={"proposalId": proposal_id})
        item          = approved_resp.get("Item")

    if not item:
        return _response(404, {"error": f"Proposal '{proposal_id}' not found"})

    return _response(200, item)


# ---------------------------------------------------------------------------
# Main Lambda handler — routes requests
# ---------------------------------------------------------------------------

def handler(event: dict, context=None) -> dict:
    """Entry point called by API Gateway. Routes based on HTTP method and path."""
    http_method = event.get("httpMethod", "")
    resource    = event.get("resource", event.get("path", ""))

    # Route: POST /generate
    if http_method == "POST" and resource == "/generate":
        return handle_generate(event)

    # Route: POST /upload-url
    if http_method == "POST" and resource == "/upload-url":
        return handle_upload_url(event)

    # Route: POST /approve
    if http_method == "POST" and resource == "/approve":
        return handle_approve(event)

    # Route: GET /proposals
    if http_method == "GET" and resource == "/proposals":
        return handle_list_proposals()

    # Route: GET /proposals/{id}
    if http_method == "GET" and (
        resource == "/proposals/{id}" or resource.startswith("/proposals/")
    ):
        path_params = event.get("pathParameters") or {}
        proposal_id = path_params.get("id") or resource.split("/proposals/", 1)[-1]
        return handle_get_proposal(proposal_id)

    # No matching route
    return _response(404, {"error": "Route not found"})
