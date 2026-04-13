# Design Document: AI-Assisted Proposal & Document Intelligence Platform

## Overview

The platform enables professionals to generate structured project proposals using Google Gemini AI. Users supply survey notes, photos, reference documents, and SOP guidelines; the AI produces a draft with per-section rationale. A human must review, optionally edit, and explicitly approve every draft before it becomes a final record. AI-generated data and human-approved truth are stored in separate DynamoDB tables and never mixed.

The system is built on a cost-optimized serverless architecture: two Lambda functions, two DynamoDB tables, one S3 bucket, and one API Gateway — all provisioned via AWS CDK TypeScript. The React + TypeScript frontend is hosted on AWS Amplify.

### Key Design Principles

- **Human-in-the-loop is mandatory**: AI drafts are always PENDING; no auto-promotion path exists.
- **Separation of AI and truth**: `proposals_draft` and `proposals_approved` are distinct tables with distinct IAM permissions.
- **Phase-gated auth**: Phase 1 uses hardcoded credentials; Phase 2 swaps in Cognito with zero UI changes.
- **Cost-optimized**: Two Lambda functions handle all backend logic; no containers, no queues.

---

## Architecture

### High-Level Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AWS Amplify Hosting                          │
│                                                                     │
│  ┌──────────────┐    ┌──────────────────────────────────────────┐  │
│  │  Login.tsx   │    │              Dashboard.tsx               │  │
│  │              │    │  ┌─────────────────┐  ┌───────────────┐  │  │
│  │  Auth_Guard  │    │  │  ProposalForm   │  │  DraftOutput  │  │  │
│  └──────┬───────┘    │  └────────┬────────┘  └───────┬───────┘  │  │
│         │            │           │                    │          │  │
│         └────────────┴───────────┴────────────────────┘          │  │
└──────────────────────────────────┬──────────────────────────────────┘
                                   │ HTTPS
                                   ▼
┌─────────────────────────────────────────────────────────────────────┐
│                          API Gateway                                │
│                                                                     │
│   POST /generate    POST /approve    POST /upload-url    GET /proposals    GET /{id}   │
└──────────┬──────────────────┬────────────────────────────────────────┘
           │                  │
           ▼                  ▼
┌──────────────────┐  ┌──────────────────────────────────────────────┐
│  generate.py     │  │              proposals.py                    │
│  (Lambda)        │  │              (Lambda)                        │
│                  │  │                                              │
│  1. Parse input  │  │  POST /approve  → write Approved_Table       │
│  2. Upload files │  │  GET /proposals → scan both tables           │
│     to S3        │  │  GET /{id}      → get from either table      │
│  3. Call Gemini  │  └──────────┬───────────────────────────────────┘
│  4. Save PENDING │             │
│     to Draft_Tbl │    ┌────────┴────────┐
└──────┬───────────┘    │                 │
       │                ▼                 ▼
       │    ┌───────────────────┐  ┌──────────────────────┐
       │    │  proposals_draft  │  │  proposals_approved  │
       │    │  (DynamoDB)       │  │  (DynamoDB)          │
       │    │  PENDING drafts   │  │  Human-approved      │
       │    │  only             │  │  final records       │
       │    └───────────────────┘  └──────────────────────┘
       │
       ▼
┌──────────────────┐    ┌──────────────────────────────────────────┐
│  S3 Bucket       │    │  Google Gemini 2.5 Flash API             │
│  (file storage)  │    │  (external — called by generate.py only) │
└──────────────────┘    └──────────────────────────────────────────┘

IAM Boundaries:
  generate.py   → R/W Draft_Table, R/W S3  (NO access to Approved_Table)
  proposals.py  → R/W Approved_Table, R   Draft_Table (NO write to Draft_Table from approve path)
```

### Phase 2 Auth Overlay (Cognito)

```
API Gateway ──► Cognito Authorizer (Phase 2 only)
                     │
                     ▼ (token validated before Lambda invocation)
              Lambda functions (unchanged)
```

### CORS Configuration

API Gateway must have CORS enabled on all routes or the React frontend will be blocked by the browser. The CDK stack configures CORS on every route:

```typescript
// in stack.ts — applied to all API Gateway routes
defaultCorsPreflightOptions: {
  allowOrigins: apigateway.Cors.ALL_ORIGINS,  // tighten to Amplify domain in production
  allowMethods: apigateway.Cors.ALL_METHODS,
  allowHeaders: ['Content-Type', 'Authorization'],
}
```

All Lambda responses must also include CORS headers:

```python
# in every Lambda response
headers = {
    "Content-Type": "application/json",
    "Access-Control-Allow-Origin": "*",
    "Access-Control-Allow-Headers": "Content-Type,Authorization",
}
```

---

## Components and Interfaces

### Frontend Components

#### `Login.tsx` (Page)
- Renders a centered card with email input, password input, and Sign In button.
- Phase 1: validates against hardcoded `admin@company.com` / `password123`.
- Phase 2: delegates to Cognito SDK — no JSX changes.
- On success: sets auth session, navigates to `/dashboard`.
- On failure: displays inline error message, stays on page.

#### `Dashboard.tsx` (Page)
- Protected by `Auth_Guard`; redirects unauthenticated users to `/`.
- Composes `ProposalForm` and `DraftOutput` side-by-side.
- Owns the draft state: passes draft data down to `DraftOutput`, passes submit handler down to `ProposalForm`.
- Handles the approve action: sends `POST /approve` with edited sections.

#### `Navbar.tsx` (Component)
- Displays app title and logout button.
- Logout clears auth session and redirects to `/`.

#### `ProposalForm.tsx` (Component)
Props: `onSubmit(formData): void`, `isLoading: boolean`, `disabled: boolean`
- Multi-line text area for survey notes.
- File input for photos (JPG, PNG).
- File input for reference documents (PDF, Word).
- File input for SOP documents (PDF, Word) — distinct from reference docs.
- Dropdown to select a past proposal as reference.
- Client-side validation: file type enforcement, at-least-one-input guard.
- Preserves all inputs on generation failure (controlled inputs).
- WHEN `isLoading` is true: Generate Draft button is disabled and shows a spinner. All file inputs and text area are disabled to prevent changes mid-request.
- Gemini calls can take 5–10 seconds — the loading state prevents double-submission and gives the user clear feedback.

#### `DraftOutput.tsx` (Component)
Props: `draft: DraftRecord | null`, `error: string | null`, `onApprove(sections): void`, `onRetry(): void`
- Renders each section with content and rationale.
- Inline edit control per section (textarea toggle).
- Tracks edited vs original content in local state.
- Shows Approve button only when a draft is present.
- Shows error message + retry button on generation failure.

### Backend Lambda Functions

#### `generate.py` — `POST /generate`

```
Input (multipart/form-data or JSON with S3 keys):
  surveyNotes: string
  photoKeys: string[]       (S3 object keys, pre-uploaded)
  documentKeys: string[]    (S3 object keys)
  sopKeys: string[]         (S3 object keys)
  referenceProposalId: string | null

Output (HTTP 200):
  proposalId: string
  status: "PENDING"
  aiGeneratedSections: Section[]
  rationale: Record<sectionName, string>
  createdAt: ISO8601
  version: 1

Error (HTTP 502):
  error: string
```

Execution flow:
1. Validate required inputs present.
2. Fetch SOP content from S3 (text extraction).
3. Fetch reference proposal from `proposals_approved` if provided.
4. Build Gemini prompt (see Gemini Prompt Structure section).
5. Call `gemini-2.5-flash` via `google-genai` SDK.
6. Parse and validate JSON response — check required sections present.
7. Generate `proposalId` (UUID), set `status=PENDING`, `version=1`, `createdAt=now()`.
8. Write record to `proposals_draft`.
9. Return full record to frontend.
10. On any Gemini error: return HTTP 502, do NOT write to DynamoDB.

#### `proposals.py` — `POST /approve`, `POST /upload-url`, `GET /proposals`, `GET /proposals/{id}`

**POST /upload-url**
```
Input:
  fileName: string
  fileType: string  (e.g. "image/jpeg", "application/pdf")

Output (HTTP 200):
  uploadUrl: string   (presigned S3 PUT URL, expires in 5 minutes)
  s3Key: string       (key to pass back in POST /generate)
```

Execution flow:
1. Generate a unique S3 key (UUID + original filename).
2. Create presigned PUT URL using boto3 `generate_presigned_url`.
3. Return URL and key to frontend.
4. Frontend uploads file directly to S3 — Lambda is not involved in the upload.

**POST /approve**
```
Input:
  proposalId: string
  finalSections: Section[]
  approvedBy: string

Output (HTTP 200):
  proposalId, finalSections, approvedBy, approvedAt, editsMade, version

Error (HTTP 404): proposalId not found in Draft_Table
```

Execution flow:
1. Fetch original draft from `proposals_draft` by `proposalId` — return 404 if missing.
2. Compute `editsMade`: diff `aiGeneratedSections` vs `finalSections` per section name.
3. Write record to `proposals_approved`.
4. Return saved record.

**GET /proposals**
- Scan `proposals_draft` (return `proposalId`, `status`, `createdAt`).
- Scan `proposals_approved` (return `proposalId`, `status="APPROVED"`, `approvedAt`).
- Merge and return combined list. Return empty list if none exist.

**GET /proposals/{id}**
- Get from `proposals_draft` first; if not found, get from `proposals_approved`.
- Return 404 if not found in either.

---

## Data Models

### `proposals_draft` DynamoDB Table

| Attribute             | Type   | Notes                                      |
|-----------------------|--------|--------------------------------------------|
| `proposalId`          | String | Partition key (UUID)                       |
| `surveyNotes`         | String | Raw user input                             |
| `aiGeneratedSections` | Map    | Array of `{sectionName, content, rationale}` |
| `rationale`           | Map    | Per-section rationale map                  |
| `status`              | String | Always `"PENDING"` in this table           |
| `createdAt`           | String | ISO 8601 timestamp                         |
| `version`             | Number | Starts at 1                                |

### `proposals_approved` DynamoDB Table

| Attribute      | Type   | Notes                                                  |
|----------------|--------|--------------------------------------------------------|
| `proposalId`   | String | Partition key (UUID) — same ID as draft                |
| `finalSections`| Map    | Array of `{sectionName, content}` — human-approved     |
| `approvedBy`   | String | User identifier                                        |
| `approvedAt`   | String | ISO 8601 timestamp                                     |
| `editsMade`    | Map    | `{sectionName: {original, final}}` for changed sections|
| `version`      | Number | Copied from draft version                              |

### Section Object Schema

```json
{
  "sectionName": "Executive Summary",
  "content": "...",
  "rationale": "This section was generated based on..."
}
```

### Required Proposal Sections (Rules Layer)

The rules layer in `generate.py` validates that the Gemini response contains all of:
- `Executive Summary`
- `Scope of Work`
- `Timeline`
- `Budget Estimate`
- `Methodology`
- `Assumptions & Exclusions`

If any required section is missing, the Lambda returns HTTP 502 and does not save.

---

## Gemini Prompt Structure

### Prompt Construction Strategy

`generate.py` uses a **rules + LLM hybrid approach**:
- Deterministic rules define the required section names and output schema.
- LLM fills the content and rationale for each section.
- Post-generation rules validate the response before saving.

### System Prompt

```
You are a professional proposal writer for [Company Name].
You follow the company's writing guidelines and standards exactly as specified in the SOP documents provided.

Your task is to generate a structured project proposal in JSON format.

COMPANY WRITING GUIDELINES (SOP):
{sop_content}

OUTPUT FORMAT — you MUST return valid JSON matching this schema exactly:
{
  "sections": [
    {
      "sectionName": "<section name>",
      "content": "<full section content>",
      "rationale": "<why this content was chosen based on the inputs>"
    }
  ]
}

Required sections (you MUST include all of these):
- Executive Summary
- Scope of Work
- Timeline
- Budget Estimate
- Methodology
- Assumptions & Exclusions

Do not include any text outside the JSON object.
```

### User Prompt

```
Generate a project proposal based on the following inputs:

SURVEY NOTES:
{survey_notes}

SITE PHOTOS:
{image_descriptions}   ← base64-encoded images passed as Gemini multimodal parts

REFERENCE PROPOSAL (for style and structure guidance):
{reference_proposal_sections}

Generate the proposal following the SOP guidelines in the system prompt.
```

### Multimodal Input Handling

Images are passed as inline base64 parts using the `google-genai` SDK:

```python
from google import genai
from google.genai import types

parts = [types.Part.from_text(user_prompt_text)]
for image_bytes in decoded_images:
    parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=[types.Content(role="user", parts=parts)],
    config=types.GenerateContentConfig(system_instruction=system_prompt)
)
```

---

## Data Flow

### S3 File Upload Flow (Presigned URLs)

The platform uses presigned URLs for all file uploads. This keeps large files out of Lambda and API Gateway (which have payload size limits) and reduces cost.

```
1. Frontend calls POST /upload-url { fileName, fileType } → API Gateway → proposals.py
2. proposals.py generates a presigned S3 PUT URL (expires in 5 minutes)
3. Frontend uploads file directly to S3 using the presigned URL (no Lambda involved)
4. Frontend receives the S3 object key
5. Frontend sends POST /generate with S3 keys (not raw file bytes)
```

This means `proposals.py` also handles `POST /upload-url` — still only 2 Lambda functions total.

---

### Generate Workflow

```
User fills ProposalForm
        │
        ▼
Frontend requests presigned URL for each file → POST /upload-url
        │
        ▼
Frontend uploads files directly to S3 using presigned URLs
        │
        ▼
Frontend sends POST /generate { surveyNotes, photoKeys, documentKeys, sopKeys, referenceProposalId }
        │
        ▼
API Gateway → generate.py Lambda
        │
        ├─► Fetch SOP content from S3
        ├─► Fetch reference proposal from proposals_approved (if provided)
        ├─► Build system prompt (SOP content injected)
        ├─► Build user prompt (survey notes + image parts + reference)
        │
        ▼
Gemini 2.5 Flash API call
        │
        ├─ Success ──► Parse JSON response
        │                    │
        │                    ├─► Rules validation (required sections present?)
        │                    │         │
        │                    │    Pass ▼
        │                    └─► Save PENDING record to proposals_draft
        │                                    │
        │                                    ▼
        │                         Return full draft to frontend
        │                                    │
        │                                    ▼
        │                         DraftOutput renders sections + rationale
        │
        └─ Failure ──► Return HTTP 502 (nothing written to DynamoDB)
                                    │
                                    ▼
                         DraftOutput shows error + retry button
                         ProposalForm preserves all inputs
```

### Approve Workflow

```
User reviews DraftOutput, optionally edits sections inline
        │
        ▼
User clicks Approve button
        │
        ▼
Frontend sends POST /approve { proposalId, finalSections, approvedBy }
        │
        ▼
API Gateway → proposals.py Lambda
        │
        ├─► GET proposalId from proposals_draft
        │         │
        │    Not found ──► Return HTTP 404
        │         │
        │    Found ──► Compute editsMade (diff AI vs final sections)
        │                    │
        │                    ▼
        │             Write to proposals_approved
        │             { proposalId, finalSections, approvedBy,
        │               approvedAt, editsMade, version }
        │                    │
        │                    ▼
        │             Return HTTP 200 with saved record
        │
        └─ (proposals_draft record remains unchanged — audit trail)
```

---

## Separation of AI Suggestions vs Authoritative Records

This is the core governance invariant of the platform:

| Concern                        | `proposals_draft`          | `proposals_approved`              |
|-------------------------------|----------------------------|-----------------------------------|
| Written by                    | `generate.py` only         | `proposals.py` (approve path) only|
| IAM write permission          | `generate.py`              | `proposals.py`                    |
| Content source                | Gemini AI                  | Human-reviewed and approved       |
| Status                        | Always `PENDING`           | Implicitly `APPROVED`             |
| Auto-promotion                | Never                      | N/A                               |
| Deleted on approve            | No (kept as audit trail)   | N/A                               |
| `editsMade` tracking          | No                         | Yes — records human changes       |

The `generate.py` Lambda has **no IAM policy** granting it access to `proposals_approved`. Even if a bug were introduced, the write would fail at the AWS permission layer.

---

## Human-in-the-Loop Checkpoints

1. **Draft Review**: After generation, the user sees every section and its AI rationale before any approval action is available.
2. **Inline Editing**: The user can modify any section; the original AI content is preserved alongside the edit until approval.
3. **Explicit Approve Action**: The Approve button is the only path to writing to `proposals_approved`. There is no background job, no auto-approve, no timer.
4. **editsMade Audit**: Every approved record captures exactly which sections were changed from the AI suggestion, providing a permanent audit trail.

---

## Error Handling

| Scenario                                  | Backend Response | Frontend Behavior                                      |
|-------------------------------------------|------------------|--------------------------------------------------------|
| Gemini API error / timeout                | HTTP 502         | Show error message, show retry button, preserve inputs |
| Gemini returns malformed JSON             | HTTP 502         | Same as above                                          |
| Gemini response missing required sections | HTTP 502         | Same as above                                          |
| POST /approve with unknown proposalId     | HTTP 404         | Show "Proposal not found" error                        |
| GET /proposals/{id} not found             | HTTP 404         | Show "Not found" message                               |
| Invalid file type on upload               | Client-side      | ProposalForm shows validation error, rejects file      |
| Empty submission (no notes, no files)     | Client-side      | ProposalForm blocks submission with validation message |
| Network failure on POST /generate         | N/A (no response)| DraftOutput treats as 502 — same error + retry flow   |

### Error Handling Implementation Notes

- `generate.py` wraps the entire Gemini call + parse + validate block in a try/except. Any exception returns HTTP 502 with `{"error": "<message>"}`. The DynamoDB write only occurs after successful validation.
- `proposals.py` uses a conditional get before writing to `proposals_approved`; missing draft returns 404 immediately.
- Frontend `DraftOutput` checks for `response.ok` and catches `fetch` exceptions — both paths set the same error state.

---

## Testing Strategy

### Unit Tests

- `generate.py`: test prompt construction, JSON parsing, section validation, error path (mock Gemini to throw).
- `proposals.py`: test editsMade diff logic, approve flow, 404 path, list merge logic.
- `ProposalForm`: test file type validation, empty submission guard, input preservation on error.
- `DraftOutput`: test section rendering, inline edit state, approve button visibility, error + retry display.

### Integration Tests

- End-to-end generate → approve flow against a local DynamoDB (e.g., DynamoDB Local).
- Verify `proposals_draft` record exists after generate; verify `proposals_approved` record exists after approve.
- Verify `generate.py` cannot write to `proposals_approved` (IAM boundary test in CDK unit tests).

### Infrastructure Tests (CDK)

- CDK assertions verify exactly 2 Lambda functions, 2 DynamoDB tables, 1 S3 bucket, 1 API Gateway.
- Verify IAM policies: `generate.py` has no `proposals_approved` write; `proposals.py` has no `proposals_draft` write.
- Snapshot tests for CDK stack output.


---

## Correctness Properties

*A property is a characteristic or behavior that should hold true across all valid executions of a system — essentially, a formal statement about what the system should do. Properties serve as the bridge between human-readable specifications and machine-verifiable correctness guarantees.*

Property-based testing is applicable here because the platform contains pure functions with clear input/output behavior: prompt construction, JSON parsing, section validation, diff computation, and form validation logic. These functions have large input spaces where varied inputs reveal edge cases. The recommended PBT library is **Hypothesis** (Python) for backend and **fast-check** (TypeScript) for frontend.

---

### Property 1: Invalid file types are always rejected

*For any* file submitted to any file input in ProposalForm (photos, documents, SOP) whose MIME type or extension is not in the allowed set for that input, the form SHALL display a validation error and not add the file to the upload list.

**Validates: Requirements 2.5, 8.2**

---

### Property 2: Empty form submission is always blocked

*For any* form state where survey notes consist entirely of whitespace (or are absent) AND no files are attached to any input, clicking Generate Draft SHALL not invoke the submit handler.

**Validates: Requirements 2.6**

---

### Property 3: Successful generation produces a valid PENDING draft record

*For any* valid Gemini JSON response containing a sections array, `generate.py` SHALL produce a record written to `proposals_draft` with: `status="PENDING"`, a UUID `proposalId`, a valid ISO 8601 `createdAt`, `version=1`, and each section containing `sectionName`, `content`, and `rationale` fields. The same record SHALL be returned in the HTTP 200 response body.

**Validates: Requirements 3.2, 3.3, 3.6**

---

### Property 4: Gemini errors never produce DynamoDB writes

*For any* error condition from Gemini (exception, timeout, malformed JSON, missing required sections), `generate.py` SHALL return HTTP 502 and SHALL make zero write calls to either `proposals_draft` or `proposals_approved`.

**Validates: Requirements 3.5, 9.3**

---

### Property 5: Generate Lambda never writes to Approved Table

*For any* input to `generate.py`, no write operation SHALL be made against the `proposals_approved` DynamoDB table — enforced both by IAM policy (no write permission granted) and by the absence of any `proposals_approved` write call in the code.

**Validates: Requirements 3.4, 5.4**

---

### Property 6: SOP content is always present in the Gemini system prompt

*For any* SOP document content extracted from S3, that content SHALL appear verbatim in the system prompt string passed to the Gemini API call.

**Validates: Requirements 8.4**

---

### Property 7: DraftOutput renders all sections with edit controls

*For any* draft object containing N sections, `DraftOutput` SHALL render exactly N section blocks, each displaying the section content and rationale, and each accompanied by an inline edit control.

**Validates: Requirements 4.1, 4.2**

---

### Property 8: Editing a section preserves the original AI content

*For any* section in `DraftOutput` that a user edits, the original AI-generated content for that section SHALL remain accessible in component state alongside the edited version until the draft is approved.

**Validates: Requirements 4.3**

---

### Property 9: Approve round-trip — saved record matches returned record

*For any* valid approve request `(proposalId, finalSections, approvedBy)` where the draft exists in `proposals_draft`, the record written to `proposals_approved` SHALL contain `proposalId`, `finalSections`, `approvedBy`, `approvedAt`, `editsMade`, and `version` — and the HTTP 200 response body SHALL match the saved record exactly.

**Validates: Requirements 5.2, 5.6**

---

### Property 10: editsMade accurately captures section diffs

*For any* pair of AI-generated sections and final sections submitted at approval, the `editsMade` field SHALL contain exactly the set of sections where `content` differs, recording both the original AI value and the final human value for each changed section. Unchanged sections SHALL NOT appear in `editsMade`.

**Validates: Requirements 5.3**

---

### Property 11: Unknown proposalId always returns 404

*For any* `proposalId` that does not exist in `proposals_draft`, a POST /approve request SHALL return HTTP 404 and make no write to `proposals_approved`. *For any* `proposalId` that does not exist in either table, a GET /proposals/{id} request SHALL return HTTP 404.

**Validates: Requirements 5.5, 6.3**

---

### Property 12: Proposal list is the complete union of both tables

*For any* state of `proposals_draft` containing N records and `proposals_approved` containing M records, GET /proposals SHALL return exactly N + M records (including the case where N=0 and M=0, returning an empty list).

**Validates: Requirements 6.1, 6.4**

---

### Property 13: GET /proposals/{id} returns the full record for any existing ID

*For any* `proposalId` that exists in either `proposals_draft` or `proposals_approved`, GET /proposals/{id} SHALL return the complete record for that ID with all stored fields.

**Validates: Requirements 6.2**

---

### Property 14: Invalid credentials always produce an error without navigation

*For any* (email, password) pair that is not the valid hardcoded credential pair, submitting the login form SHALL display an error message and SHALL NOT navigate to the Dashboard.

**Validates: Requirements 1.3**

---

### Property 15: Unauthenticated access always redirects to Login

*For any* unauthenticated session state, any attempt to render or navigate to the Dashboard SHALL result in a redirect to the Login page.

**Validates: Requirements 1.4**

---

### Property 16: Generation failure preserves all form inputs

*For any* form state at the time of a generation failure (HTTP 502 or network error), all user-entered inputs — survey notes, uploaded files, and selected reference proposal — SHALL remain unchanged after the failure, and `DraftOutput` SHALL display an error message and a retry button.

**Validates: Requirements 9.1, 9.2, 9.4**
