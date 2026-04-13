"""
generate.py
-----------
AWS Lambda handler for POST /generate

Async pattern to avoid API Gateway 29s timeout:
  1. POST /generate saves a PROCESSING record immediately, invokes this Lambda
     async (Event invocation type), and returns the proposalId right away
  2. The async invocation runs Gemini and updates the record to PENDING when done
  3. Frontend polls GET /proposals/{id} until status != PROCESSING

On any error: updates the record status to ERROR.
"""

import json
import os
import uuid
from datetime import datetime, timezone

import boto3
from google import genai
from google.genai import types

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

DRAFT_TABLE_NAME     = os.environ.get("DRAFT_TABLE_NAME", "proposals_draft")
APPROVED_TABLE_NAME  = os.environ.get("APPROVED_TABLE_NAME", "proposals_approved")
UPLOADS_BUCKET_NAME  = os.environ.get("UPLOADS_BUCKET_NAME", "uploads-bucket")
GEMINI_API_KEY_PARAM = os.environ.get("GEMINI_API_KEY_PARAM", "/ai-proposal/gemini-api-key")
FUNCTION_NAME        = os.environ.get("AWS_LAMBDA_FUNCTION_NAME", "ai-proposal-generate")

dynamodb      = boto3.resource("dynamodb")
s3_client     = boto3.client("s3")
ssm_client    = boto3.client("ssm")
lambda_client = boto3.client("lambda")

CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
}

REQUIRED_SECTIONS = [
    "Executive Summary",
    "Scope of Work",
    "Timeline",
    "Budget Estimate",
    "Methodology",
    "Assumptions & Exclusions",
]

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
# Helpers
# ---------------------------------------------------------------------------

def _response(status_code, body):
    return {"statusCode": status_code, "headers": CORS_HEADERS, "body": json.dumps(body)}

def _get_gemini_api_key():
    resp = ssm_client.get_parameter(Name=GEMINI_API_KEY_PARAM, WithDecryption=True)
    return resp["Parameter"]["Value"]

def _build_system_prompt(sop_content):
    return SYSTEM_PROMPT_TEMPLATE.format(sop_content=sop_content)

def _build_user_prompt(survey_notes, reference_sections):
    lines = ["Generate a project proposal based on the following inputs:", "\nSURVEY NOTES:", survey_notes or "(none provided)"]
    if reference_sections:
        lines.append("\nREFERENCE PROPOSAL (for style and structure guidance):")
        for sec in reference_sections:
            lines.append(f"  [{sec.get('sectionName', '')}]: {sec.get('content', '')}")
    return "\n".join(lines)

def _fetch_sop_content(sop_keys):
    parts = []
    for key in sop_keys:
        obj = s3_client.get_object(Bucket=UPLOADS_BUCKET_NAME, Key=key)
        parts.append(obj["Body"].read().decode("utf-8", errors="replace"))
    return "\n\n".join(parts)

def _fetch_image_bytes(photo_keys):
    images = []
    for key in photo_keys:
        obj = s3_client.get_object(Bucket=UPLOADS_BUCKET_NAME, Key=key)
        images.append(obj["Body"].read())
    return images

def _fetch_reference_sections(reference_proposal_id):
    table = dynamodb.Table(APPROVED_TABLE_NAME)
    resp = table.get_item(Key={"proposalId": reference_proposal_id})
    item = resp.get("Item")
    return item.get("finalSections", []) if item else []

def _parse_and_validate_response(raw_text):
    text = raw_text.strip()
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
    present = {s.get("sectionName") for s in sections}
    missing = [name for name in REQUIRED_SECTIONS if name not in present]
    if missing:
        raise ValueError(f"Gemini response missing required sections: {missing}")
    return sections

# ---------------------------------------------------------------------------
# Async worker — runs the actual Gemini call (invoked async by handler)
# ---------------------------------------------------------------------------

def _run_generation(body, proposal_id):
    """Called asynchronously — does the heavy Gemini work and updates DynamoDB."""
    import time
    draft_table = dynamodb.Table(DRAFT_TABLE_NAME)

    try:
        survey_notes          = body.get("surveyNotes", "").strip()
        photo_keys            = body.get("photoKeys") or []
        sop_keys              = body.get("sopKeys") or []
        reference_proposal_id = body.get("referenceProposalId")

        sop_content        = _fetch_sop_content(sop_keys) if sop_keys else "(No SOP documents provided)"
        reference_sections = _fetch_reference_sections(reference_proposal_id) if reference_proposal_id else []
        system_prompt      = _build_system_prompt(sop_content)
        user_prompt_text   = _build_user_prompt(survey_notes, reference_sections)
        image_bytes_list   = _fetch_image_bytes(photo_keys) if photo_keys else []

        parts = [types.Part.from_text(text=user_prompt_text)]
        for image_bytes in image_bytes_list:
            parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))

        client   = genai.Client(api_key=_get_gemini_api_key())
        response = None
        last_exc = None
        for attempt in range(5):
            try:
                response = client.models.generate_content(
                    model="models/gemini-2.5-flash",
                    contents=[types.Content(role="user", parts=parts)],
                    config=types.GenerateContentConfig(system_instruction=system_prompt),
                )
                break
            except Exception as exc:
                last_exc = exc
                err_str = str(exc)
                if attempt < 4 and ("503" in err_str or "UNAVAILABLE" in err_str or "overloaded" in err_str.lower()):
                    time.sleep(5 * (attempt + 1))  # 5s, 10s, 15s, 20s backoff
                else:
                    break
        if response is None:
            raise last_exc

        sections = _parse_and_validate_response(response.text)

        # Update the record from PROCESSING → PENDING with the AI sections
        draft_table.update_item(
            Key={"proposalId": proposal_id},
            UpdateExpression="SET #s = :s, aiGeneratedSections = :sec",
            ExpressionAttributeNames={"#s": "status"},
            ExpressionAttributeValues={":s": "PENDING", ":sec": sections},
        )

    except Exception as exc:
        # Mark as ERROR so frontend stops polling, then delete after a short delay
        try:
            draft_table.update_item(
                Key={"proposalId": proposal_id},
                UpdateExpression="SET #s = :s, errorMessage = :e",
                ExpressionAttributeNames={"#s": "status"},
                ExpressionAttributeValues={":s": "ERROR", ":e": str(exc)},
            )
        except Exception:
            pass
        # Delete the failed record — no point keeping ERROR drafts in the table
        try:
            import time as _time
            _time.sleep(2)  # brief delay so frontend can read the ERROR status once
            draft_table.delete_item(Key={"proposalId": proposal_id})
        except Exception:
            pass

# ---------------------------------------------------------------------------
# Main Lambda handler
# ---------------------------------------------------------------------------

def handler(event, context=None):
    # Async invocation from self — run the generation worker
    if event.get("_async"):
        _run_generation(event.get("body", {}), event["proposalId"])
        return

    # Sync invocation from API Gateway
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        body = {}

    survey_notes  = body.get("surveyNotes", "").strip()
    photo_keys    = body.get("photoKeys") or []
    document_keys = body.get("documentKeys") or []
    sop_keys      = body.get("sopKeys") or []

    if not survey_notes and not (photo_keys or document_keys or sop_keys):
        return _response(400, {"error": "Request must include surveyNotes or at least one file key"})

    # Create a PROCESSING placeholder record immediately
    proposal_id = str(uuid.uuid4())
    created_at  = datetime.now(timezone.utc).isoformat()
    record = {
        "proposalId":          proposal_id,
        "surveyNotes":         survey_notes,
        "aiGeneratedSections": [],
        "status":              "PROCESSING",  # Will become PENDING when Gemini finishes
        "createdAt":           created_at,
        "version":             1,
    }
    dynamodb.Table(DRAFT_TABLE_NAME).put_item(Item=record)

    # Invoke this Lambda asynchronously to do the actual Gemini call
    lambda_client.invoke(
        FunctionName=FUNCTION_NAME,
        InvocationType="Event",  # Async — returns immediately
        Payload=json.dumps({"_async": True, "proposalId": proposal_id, "body": body}),
    )

    # Return the proposalId immediately — frontend will poll for completion
    return _response(202, {"proposalId": proposal_id, "status": "PROCESSING"})
