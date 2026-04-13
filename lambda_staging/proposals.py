"""
proposals.py
------------
AWS Lambda handler for proposal management endpoints:
  - POST /upload-url    → Generate a pre-signed S3 URL for file uploads
  - POST /approve       → Approve a draft proposal and move it to approved table
  - GET  /proposals     → List all proposals (drafts + approved)
  - GET  /proposals/{id} → Get a single proposal by ID

Human-in-the-loop governance:
  - AI drafts are stored in proposals_draft with status PENDING
  - Only after human review and approval are they moved to proposals_approved
  - Edit tracking: differences between AI draft and final approved version are recorded
"""

import json
import os
import uuid
from datetime import datetime, timezone
from decimal import Decimal

import boto3

# ---------------------------------------------------------------------------
# Config — read from Lambda environment variables set by CDK
# ---------------------------------------------------------------------------

DRAFT_TABLE_NAME    = os.environ.get("DRAFT_TABLE_NAME", "proposals_draft")
APPROVED_TABLE_NAME = os.environ.get("APPROVED_TABLE_NAME", "proposals_approved")
UPLOADS_BUCKET_NAME = os.environ.get("UPLOADS_BUCKET_NAME", "uploads-bucket")

# AWS clients
dynamodb  = boto3.resource("dynamodb")
s3_client = boto3.client("s3")

# CORS headers — allow requests from any origin (frontend)
CORS_HEADERS = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
}


class DecimalEncoder(json.JSONEncoder):
    """Custom JSON encoder to handle DynamoDB Decimal types."""
    def default(self, obj):
        if isinstance(obj, Decimal):
            # Convert Decimal to int if whole number, else float
            return int(obj) if obj % 1 == 0 else float(obj)
        return super().default(obj)


def _response(status_code: int, body: object) -> dict:
    """Build a standard API Gateway response with CORS headers."""
    return {
        "statusCode": status_code,
        "headers": CORS_HEADERS,
        "body": json.dumps(body, cls=DecimalEncoder),
    }


# ---------------------------------------------------------------------------
# POST /upload-url — Generate pre-signed S3 URL for file upload
# ---------------------------------------------------------------------------

def handle_upload_url(event: dict) -> dict:
    """
    Generates a pre-signed S3 PUT URL so the frontend can upload files
    directly to S3 without going through the Lambda.
    Returns: { uploadUrl, s3Key }
    """
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        body = {}

    file_name = body.get("fileName", "upload")
    file_type = body.get("fileType", "application/octet-stream")

    # Generate a unique S3 key to avoid filename collisions
    s3_key = f"uploads/{uuid.uuid4()}/{file_name}"

    # Create a pre-signed URL valid for 5 minutes
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


# ---------------------------------------------------------------------------
# POST /approve — Human approves a draft proposal
# ---------------------------------------------------------------------------

def _compute_edits_made(ai_sections: list, final_sections: list) -> dict:
    """
    Compare AI-generated sections vs human-edited final sections.
    Returns a dict of sections where the human made changes.
    This provides an audit trail of what the reviewer changed.
    """
    ai_by_name = {s["sectionName"]: s.get("content", "") for s in ai_sections}
    edits_made = {}
    for section in final_sections:
        name          = section["sectionName"]
        final_content = section.get("content", "")
        ai_content    = ai_by_name.get(name, "")
        if final_content != ai_content:
            # Record what the AI wrote vs what the human changed it to
            edits_made[name] = {"original": ai_content, "final": final_content}
    return edits_made


def handle_approve(event: dict) -> dict:
    """
    Approves a draft proposal:
    1. Loads the draft from proposals_draft table
    2. Computes what edits the reviewer made vs the AI draft
    3. Saves the approved version to proposals_approved table
    4. Updates the draft status from PENDING to APPROVED
    """
    try:
        body = json.loads(event.get("body") or "{}")
    except (json.JSONDecodeError, TypeError):
        body = {}

    proposal_id    = body.get("proposalId")
    final_sections = body.get("finalSections", [])  # Human-edited sections
    approved_by    = body.get("approvedBy", "")

    if not proposal_id:
        return _response(400, {"error": "proposalId is required"})

    # Load the original AI draft from DynamoDB
    draft_table = dynamodb.Table(DRAFT_TABLE_NAME)
    draft_resp  = draft_table.get_item(Key={"proposalId": proposal_id})
    draft       = draft_resp.get("Item")

    if not draft:
        return _response(404, {"error": f"Proposal '{proposal_id}' not found in draft table"})

    # Calculate what the reviewer changed from the AI draft
    ai_sections = draft.get("aiGeneratedSections", [])
    edits_made  = _compute_edits_made(ai_sections, final_sections)

    # Build the approved record
    approved_at = datetime.now(timezone.utc).isoformat()
    record = {
        "proposalId":    proposal_id,
        "finalSections": final_sections,  # Human-approved final content
        "approvedBy":    approved_by,
        "approvedAt":    approved_at,
        "editsMade":     edits_made,       # Audit trail of human edits
        "version":       draft.get("version", 1),
    }

    # Save to approved table (authoritative record)
    approved_table = dynamodb.Table(APPROVED_TABLE_NAME)
    approved_table.put_item(Item=record)

    # Update draft status to APPROVED so it's clear it's been reviewed
    draft_table.update_item(
        Key={"proposalId": proposal_id},
        UpdateExpression="SET #s = :s",
        ExpressionAttributeNames={"#s": "status"},
        ExpressionAttributeValues={":s": "APPROVED"},
    )

    return _response(200, record)


# ---------------------------------------------------------------------------
# GET /proposals — List all proposals
# ---------------------------------------------------------------------------

def handle_list_proposals() -> dict:
    """
    Returns a combined list of all draft and approved proposals.
    Used by the frontend dropdown to select a reference proposal.
    """
    draft_table    = dynamodb.Table(DRAFT_TABLE_NAME)
    approved_table = dynamodb.Table(APPROVED_TABLE_NAME)

    # Scan draft table — only return summary fields
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

    # Scan approved table — only return summary fields
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


# ---------------------------------------------------------------------------
# GET /proposals/{id} — Get a single proposal by ID
# ---------------------------------------------------------------------------

def handle_get_proposal(proposal_id: str) -> dict:
    """
    Fetches a single proposal by ID.
    Checks draft table first, then approved table.
    """
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
# Main Lambda handler — routes requests to the correct function
# ---------------------------------------------------------------------------

def handler(event: dict, context) -> dict:
    """
    Entry point called by API Gateway.
    Routes based on HTTP method and path.
    """
    http_method = event.get("httpMethod", "")
    resource    = event.get("resource", event.get("path", ""))

    # Route: POST /upload-url — get S3 pre-signed URL for file upload
    if http_method == "POST" and resource == "/upload-url":
        return handle_upload_url(event)

    # Route: POST /approve — human approves a draft
    if http_method == "POST" and resource == "/approve":
        return handle_approve(event)

    # Route: GET /proposals — list all proposals
    if http_method == "GET" and resource == "/proposals":
        return handle_list_proposals()

    # Route: GET /proposals/{id} — get single proposal
    if http_method == "GET" and (
        resource == "/proposals/{id}" or resource.startswith("/proposals/")
    ):
        path_params = event.get("pathParameters") or {}
        proposal_id = path_params.get("id") or resource.split("/proposals/", 1)[-1]
        return handle_get_proposal(proposal_id)

    # No matching route found
    return _response(404, {"error": "Route not found"})
