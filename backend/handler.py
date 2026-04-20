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
dynamodb      = boto3.resource("dynamodb")
s3_client     = boto3.client("s3")
ssm_client    = boto3.client("ssm")
lambda_client = boto3.client("lambda")

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
    """POST /generate — Kick off async AI proposal generation and return proposalId immediately."""
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

    # Create proposal record immediately with PROCESSING status
    proposal_id = str(uuid.uuid4())
    created_at  = datetime.now(timezone.utc).isoformat()
    draft_table = dynamodb.Table(DRAFT_TABLE_NAME)
    draft_table.put_item(Item={
        "proposalId": proposal_id,
        "status":     "PROCESSING",
        "createdAt":  created_at,
        "version":    1,
    })

    # Fire async Lambda self-invocation to do the heavy Gemini work
    function_name = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "ai-proposal-unified")
    lambda_client.invoke(
        FunctionName=function_name,
        InvocationType="Event",  # async — no wait
        Payload=json.dumps({
            "_async_generate": True,
            "proposalId":           proposal_id,
            "surveyNotes":          survey_notes,
            "photoKeys":            photo_keys,
            "documentKeys":         document_keys,
            "sopKeys":              sop_keys,
            "referenceProposalId":  reference_proposal_id,
        }).encode(),
    )

    return _response(200, {"proposalId": proposal_id, "status": "PROCESSING"})


def _handle_async_generate(event: dict) -> None:
    """Internal: called asynchronously to run Gemini generation and update DynamoDB."""
    proposal_id           = event["proposalId"]
    survey_notes          = event.get("surveyNotes", "")
    photo_keys            = event.get("photoKeys") or []
    sop_keys              = event.get("sopKeys") or []
    reference_proposal_id = event.get("referenceProposalId")
    draft_table           = dynamodb.Table(DRAFT_TABLE_NAME)

    try:
        sop_content        = _fetch_sop_content(sop_keys) if sop_keys else "(No SOP documents provided)"
        reference_sections = _fetch_reference_sections(reference_proposal_id) if reference_proposal_id else []
        system_prompt      = _build_system_prompt(sop_content)
        user_prompt_text   = _build_user_prompt(survey_notes, reference_sections)
        image_bytes_list   = _fetch_image_bytes(photo_keys) if photo_keys else []

        parts = [types.Part.from_text(text=user_prompt_text)]
        for image_bytes in image_bytes_list:
            parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))

        client   = genai.Client(api_key=_get_gemini_api_key())
        last_exc = None
        response = None
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
                    time.sleep(min(wait, 50))
                else:
                    break

        if response is None:
            raise last_exc

        sections = _parse_and_validate_response(response.text)

        draft_table.update_item(
            Key={"proposalId": proposal_id},
            UpdateExpression="SET #s = :s, aiGeneratedSections = :sec, surveyNotes = :sn",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "PENDING", ":sec": sections, ":sn": survey_notes},
        )

    except Exception as exc:
        err_str = str(exc)
        if "429" in err_str or "RESOURCE_EXHAUSTED" in err_str:
            clean_error = "Gemini API quota exceeded. Please wait a few minutes and try again, or upgrade your Gemini API plan."
        elif "503" in err_str or "UNAVAILABLE" in err_str:
            clean_error = "Gemini AI is currently overloaded. Please wait a moment and try again."
        else:
            clean_error = err_str
        draft_table.update_item(
            Key={"proposalId": proposal_id},
            UpdateExpression="SET #s = :s, errorMessage = :e",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "ERROR", ":e": clean_error},
        )


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
    """GET /proposals — List all proposals (deduped, approved takes priority)."""
    draft_table    = dynamodb.Table(DRAFT_TABLE_NAME)
    approved_table = dynamodb.Table(APPROVED_TABLE_NAME)

    draft_result = draft_table.scan(
        ProjectionExpression="proposalId, #s, createdAt",
        ExpressionAttributeNames={"#s": "status"},
    )
    approved_result = approved_table.scan(
        ProjectionExpression="proposalId, approvedAt",
    )

    proposals: dict = {}

    for item in draft_result.get("Items", []):
        pid = item["proposalId"]
        proposals[pid] = {
            "proposalId": pid,
            "status":     item.get("status", "PENDING"),
            "createdAt":  item.get("createdAt"),
        }

    # Approved overrides draft entry for same proposalId
    for item in approved_result.get("Items", []):
        pid = item["proposalId"]
        proposals[pid] = {
            "proposalId": pid,
            "status":     "APPROVED",
            "approvedAt": item.get("approvedAt"),
        }

    return _response(200, list(proposals.values()))


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

    # Internal async invocation from handle_generate
    if event.get("_async_generate"):
        _handle_async_generate(event)
        return {}

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
