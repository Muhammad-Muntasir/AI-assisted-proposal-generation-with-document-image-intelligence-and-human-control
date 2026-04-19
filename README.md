# AI-Assisted Proposal & Document Intelligence Platform

A serverless platform that helps professionals generate structured project proposals using Google Gemini AI. Users supply survey notes, site photos, reference documents, and company SOP guidelines — the AI produces a draft with per-section rationale. Every draft must be reviewed, optionally edited, and explicitly approved by a human before it becomes a final record.

Built for: project managers, consultants, and field professionals who need high-quality proposal drafts fast without sacrificing accuracy or accountability.

---

## AI Approach

### Model

Google Gemini 2.5 Flash, accessed via the `google-genai` Python SDK.

### Rules + LLM Hybrid

`generate.py` uses a two-layer approach:

- **Deterministic rules layer** — defines the required output schema and the six required section names (`Executive Summary`, `Scope of Work`, `Timeline`, `Budget Estimate`, `Methodology`, `Assumptions & Exclusions`). These are enforced before and after the Gemini call.
- **LLM layer** — Gemini fills the content and rationale for each section based on the inputs provided.

This means the structure is always predictable and machine-verifiable, while the content remains contextually rich.

### Prompt Orchestration in `handler.py`

The unified Lambda handler routes all API requests and follows this sequence on every `POST /generate` request:

1. Validate inputs — require at least survey notes or one file key.
2. Fetch SOP document content from S3 (see SOP section below).
3. Fetch reference proposal sections from `proposals_approved` if a reference ID was provided.
4. Build the **system prompt** — injects SOP content verbatim as company writing guidelines.
5. Build the **user prompt** — combines survey notes, reference proposal sections, and base64-encoded site photos as multimodal parts.
6. Call `gemini-2.5-flash` via the `google-genai` SDK with the system prompt and multimodal user content.
7. Parse the JSON response and validate all six required sections are present.
8. On success: generate a UUID `proposalId`, set `status=PENDING`, `version=1`, write to `proposals_draft`, return the full record.
9. On any error (Gemini exception, malformed JSON, missing sections): return HTTP 502, write nothing to DynamoDB.

Images are passed as inline multimodal parts:

```python
parts = [types.Part.from_text(text=user_prompt_text)]
for image_bytes in image_bytes_list:
    parts.append(types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg"))

response = client.models.generate_content(
    model="gemini-2.5-flash",
    contents=[types.Content(role="user", parts=parts)],
    config=types.GenerateContentConfig(system_instruction=system_prompt),
)
```

---

## SOP Document Support

SOP (Standard Operating Procedure) documents define a company's writing guidelines and standards. They are treated as a distinct input type — separate from reference proposals and site photos.

**How it works:**

1. The user uploads SOP documents (PDF or Word) via the `ProposalForm`.
2. The frontend requests a presigned S3 PUT URL for each file via `POST /upload-url`, then uploads directly to S3.
3. The S3 object keys are sent to `POST /generate` in the `sopKeys` field.
4. `handler.py` fetches the SOP files from S3 and reads their text content.
5. The extracted text is injected **verbatim** into the Gemini system prompt under the `COMPANY WRITING GUIDELINES (SOP):` heading.
6. Gemini receives the SOP content as authoritative instructions before generating any proposal content.

This means the AI is not summarizing or interpreting the SOPs — it receives the full text and is instructed to follow it exactly.

---

## Governance

### AI Authority — What Should Never Be Fully Automated

Final pricing, legal scope definitions, and client commitments must always require human sign-off. These decisions carry financial and legal accountability that AI cannot reliably provide. Gemini generates estimates and scope language as a starting point, but a human must review and explicitly approve before any content becomes a final record. There is no auto-approve path in this system.

### Explainability — How AI-Generated Scopes Are Made Understandable

Every section in the AI draft includes a `rationale` field that explains why that content was generated based on the inputs provided. Users can see exactly what drove each section before approving. The reference proposal and SOP inputs are also visible in the form, so the source of the AI's guidance is traceable.

### Data Integrity — How AI Outputs Are Prevented from Polluting Historical Data

The platform uses two completely separate DynamoDB tables with distinct IAM permissions:

- `proposals_draft` — written only by the unified Lambda. Stores AI-generated drafts with `status=PENDING`.
- `proposals_approved` — written only by the unified Lambda on an explicit `POST /approve` request. Stores human-approved final records.

The Lambda has write access to both tables but enforces strict separation through application logic. AI-generated content can never reach the approved table without a human explicitly triggering the approve action.

### Failure Modes — How the System Behaves When AI Is Incomplete or Unavailable

If Gemini returns an error, times out, returns malformed JSON, or returns a response missing any required section:

- The unified Lambda returns HTTP 502 with a descriptive error message.
- Nothing is written to DynamoDB — no partial or empty draft records are created.
- The frontend `DraftOutput` component displays a user-friendly error message and a retry button.
- `ProposalForm` preserves all user inputs (survey notes, uploaded files, selected reference) so the user can retry without re-entering data.

---

## Known Limitations and Next Steps

**Current limitations:**

- Authentication uses hardcoded credentials (`admin@company.com` / `password123`) — not suitable for production.
- SOP text extraction is basic UTF-8 decode; binary PDF/Word formats require a proper extraction library (e.g., `pypdf`, `python-docx`) to work correctly.
- No pagination on `GET /proposals` — will degrade at scale.
- Gemini calls can take 5–10 seconds; there is no streaming or progress indicator beyond the loading spinner.
- File uploads go through presigned URLs but there is no virus scanning or content validation on S3.
- The `proposals_draft` table is never pruned; old PENDING drafts accumulate indefinitely.

**Planned next steps:**

- Phase 2: Replace hardcoded auth with AWS Cognito (zero UI changes required — the `Auth_Guard` is already designed for this swap).
- Add proper PDF/Word text extraction using `pypdf` and `python-docx`.
- Add DynamoDB TTL on `proposals_draft` to auto-expire old drafts.
- Tighten CORS to the specific Amplify domain instead of `*`.
- Add CloudWatch alarms for Lambda error rates and Gemini API latency.
- Add streaming response support for faster perceived generation time.

---

## Deployment Instructions

### Prerequisites

- Node.js 18+
- Python 3.11+
- AWS CLI configured with appropriate credentials (`aws configure`)
- AWS CDK CLI: `npm install -g aws-cdk`
- A Google Gemini API key

> CDK bootstrap has already been run for this AWS account/region. If deploying to a new account or region, run `cdk bootstrap` first.

---

### 1. Store the Gemini API Key in SSM

```bash
aws ssm put-parameter \
  --name "/ai-proposal-platform/gemini-api-key" \
  --value "YOUR_GEMINI_API_KEY" \
  --type SecureString
```

---

### 2. Backend — Install Python Dependencies

```bash
pip install -r backend/requirements.txt
```

---

### 3. Infrastructure — Deploy via CDK

```bash
cd infrastructure
npm install
cdk deploy
```

CDK will output the API Gateway URL. Copy it — you'll need it for the frontend.

---

### 4. Frontend — Build and Connect to Amplify

Create the frontend environment file:

```bash
cd frontend
cp .env.example .env
```

Edit `frontend/.env` and set:

```
VITE_API_URL=https://your-api-gateway-url.execute-api.region.amazonaws.com/prod
```

Install dependencies and build:

```bash
npm install
npm run build
```

Then connect the `frontend/` directory to AWS Amplify Hosting:

1. Open the AWS Amplify console.
2. Create a new app and connect your Git repository, or use the Amplify CLI to deploy the `frontend/dist/` build output manually.
3. Set the `VITE_API_URL` environment variable in the Amplify console under App settings → Environment variables.

---

### Environment Variables Summary

| Variable | Where | Description |
|---|---|---|
| `GEMINI_API_KEY` | AWS SSM Parameter Store | Gemini API key, injected into `generate.py` Lambda at deploy time |
| `VITE_API_URL` | `frontend/.env` and Amplify console | API Gateway base URL for the React frontend |

---

## Project Structure

```
.
├── backend/
│   ├── handler.py           # Unified Lambda: handles all endpoints (generate, approve, upload-url, proposals)
│   ├── requirements.txt     # Python dependencies
│   └── tests/               # Unit and property-based tests (Hypothesis)
│
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── ProposalForm.tsx   # File upload, survey notes, SOP input, submit
│   │   │   ├── DraftOutput.tsx    # Section rendering, inline editing, approve button
│   │   │   ├── AuthGuard.tsx      # Redirects unauthenticated users to login
│   │   │   └── Navbar.tsx         # App title and logout
│   │   ├── pages/
│   │   │   ├── Login.tsx          # Auth page (Phase 1: hardcoded, Phase 2: Cognito)
│   │   │   └── Dashboard.tsx      # Main protected page — composes form and draft output
│   │   └── auth.ts                # Session management helpers
│   └── .env.example               # Environment variable template
│
└── infrastructure/
    └── src/
        ├── stack.ts           # CDK stack — all AWS resources defined here
        └── main.ts            # CDK app entry point
```
