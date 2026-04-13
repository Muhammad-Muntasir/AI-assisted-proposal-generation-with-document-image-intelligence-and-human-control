"""
generate.py
-----------
AWS Lambda handler for POST /generate

What it does:
  1. Receives survey notes, optional photo/document S3 keys from the frontend
  2. Fetches the Gemini API key securely from AWS SSM Parameter Store
  3. Optionally loads SOP documents and reference proposals from S3
  4. Calls Google Gemini AI to generate a structured proposal draft
  5. Validates the AI response has all required sections
  6. Saves the draft to DynamoDB (proposals_draft table) with status PENDING
  7. Returns the full draft record to the frontend

On any error: returns HTTP 502 and writes nothing to DynamoDB.
"""

import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# Config — read from Lambda environment variables set by CDK
# ---------------------------------------------------------------------------

DRAFT_TABLE_NAME     = os.environ.get("DRAFT_TABLE_NAME", "proposals_draft")
APPROVED_TABLE_NAME  = os.environ.get("APPROVED_TABLE_NAME", "proposals_approved")
UPLOADS_BUCKET_NAME  = os.environ.get("UPLOADS_BUCKET_NAME", "uploads-bucket")
GEMINI_API_KEY_PARAM = os.environ.get("GEMINI_API_KEY_PARAM", "/ai-proposal/gemini-api-key")

# AWS clients
dynamodb   = boto3.resource("dynamodb")
s3_client  = boto3.client("s3")
ssm_client = boto3.client("ssm")

# CORS headers — allow requests from any origin (frontend)
CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
}

# These sections MUST be present in every AI-generated proposal
REQUIRED_SECTIONS = [
    "Executive Summary",
    "Scope of Work",
    "Timeline",
    "Budget Estimate",
    "Methodology",
    "Assumptions & Exclusions",
]

# System prompt template — tells Gemini how to behave and what format to return
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

def _response(status_code: int, body: object) -> dict:
    """Build a standard API Gateway response with CORS headers."""
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body),
    }


def _get_gemini_api_key() -> str:
    """Fetch the Gemini API key from AWS SSM Parameter Store (encrypted)."""
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
        # Include past approved proposal sections as style reference
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
    """
    Parse the AI response JSON and check all required sections are present.
    Strips markdown code fences if Gemini wraps the JSON in them.
    Raises ValueError if the response is invalid or missing sections.
    """
    text = raw_text.strip()

    # Remove markdown code fences (```json ... ```) if present
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


# ---------------------------------------------------------------------------
# Main Lambda handler — entry point called by API Gateway
# ---------------------------------------------------------------------------

def handler(event: dict, context=None) -> dict:
    # Parse the request body from API Gateway event
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        body = {}

    # Extract inputs from request
    survey_notes       = body.get("surveyNotes", "").strip()
    photo_keys         = body.get("photoKeys") or []        # S3 keys for uploaded photos
    document_keys      = body.get("documentKeys") or []     # S3 keys for reference docs
    sop_keys           = body.get("sopKeys") or []          # S3 keys for SOP documents
    reference_proposal_id = body.get("referenceProposalId") # Optional past proposal ID

    # Validate — must have at least survey notes or a file
    has_notes = bool(survey_notes)
    has_files = bool(photo_keys or document_keys or sop_keys)
    if not has_notes and not has_files:
        return _response(400, {"error": "Request must include surveyNotes or at least one file key"})

    try:
        # Step 1: Load SOP guidelines from S3 (if provided)
        sop_content = _fetch_sop_content(sop_keys) if sop_keys else "(No SOP documents provided)"

        # Step 2: Load reference proposal sections from DynamoDB (if provided)
        reference_sections = []
        if reference_proposal_id:
            reference_sections = _fetch_reference_sections(reference_proposal_id)

        # Step 3: Build the AI prompts
        system_prompt    = _build_system_prompt(sop_content)
        user_prompt_text = _build_user_prompt(survey_notes, reference_sections)

        # Step 4: Download site photos from S3 for multimodal input
        image_bytes_list = _fetch_image_bytes(photo_keys) if photo_keys else []

        # Build multimodal content parts (text + images)
        parts = [types.Part.from_text(text=user_prompt_text)]
        for image_bytes in image_bytes_list:
            parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))

        # Step 5: Call Gemini AI with retry on 429 (rate limit) and 503 (overload)
        import time, re
        client   = genai.Client(api_key=_get_gemini_api_key())
        last_exc = None
        for attempt in range(4):  # Up to 4 attempts
            try:
                response = client.models.generate_content(
                    model="gemini-1.5-flash",  # Using 1.5-flash for higher free tier quota
                    contents=[types.Content(role="user", parts=parts)],
                    config=types.GenerateContentConfig(system_instruction=system_prompt),
                )
                break  # Success — exit retry loop
            except Exception as exc:
                last_exc = exc
                err_str = str(exc)
                # Check if this is a retryable error (429 rate limit or 503 overload)
                is_rate_limit = "429" in err_str or "RESOURCE_EXHAUSTED" in err_str
                is_overloaded = "503" in err_str or "UNAVAILABLE" in err_str
                if attempt < 3 and (is_rate_limit or is_overloaded):
                    # Try to extract the retryDelay Gemini suggests (e.g. "retryDelay: 45s")
                    match = re.search(r"retryDelay['\"]?\s*[:\s]+['\"]?(\d+)", err_str)
                    wait = int(match.group(1)) if match else (45 if is_rate_limit else 5)
                    wait = min(wait, 50)  # Cap at 50s to stay within Lambda timeout
                    time.sleep(wait)
                else:
                    break  # Non-retryable error or out of attempts
        else:
            pass  # Loop completed without break — last_exc holds the error
        if last_exc and 'response' not in dir():
            raise last_exc

        # Step 6: Parse and validate the AI response
        sections = _parse_and_validate_response(response.text)

        # Step 7: Build the draft record to save
        proposal_id = str(uuid.uuid4())
        created_at  = datetime.now(timezone.utc).isoformat()

        record = {
            "proposalId":          proposal_id,
            "surveyNotes":         survey_notes,
            "aiGeneratedSections": sections,   # AI-generated content (not yet approved)
            "status":              "PENDING",  # Human review required before approval
            "createdAt":           created_at,
            "version":             1,
        }

        # Step 8: Save draft to DynamoDB
        draft_table = dynamodb.Table(DRAFT_TABLE_NAME)
        draft_table.put_item(Item=record)

        # Step 9: Return the full draft to the frontend
        return _response(200, record)

    except Exception as exc:
        # Return 502 on any unexpected error — nothing is saved to DynamoDB
        return _response(502, {"error": str(exc)})
