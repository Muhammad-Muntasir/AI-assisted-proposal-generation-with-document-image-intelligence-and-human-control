# Implementation Plan: AI-Assisted Proposal & Document Intelligence Platform

## Overview

Incremental implementation starting with infrastructure, then backend Lambda functions, then the React frontend. Each step builds on the previous and ends with all components wired together.

## Tasks

- [x] 1. Set up project structure and CDK infrastructure
  - Create root `.gitignore` covering `node_modules/`, `__pycache__/`, `*.pyc`, `infrastructure/dist/`, `infrastructure/cdk.out/`, `.env`, `.env.local`, `frontend/.amplify/`, `.DS_Store`, `.vscode/`, `.idea/`
  - Create `backend/requirements.txt` with `google-genai`, `boto3`, `Pillow`
  - Initialize CDK TypeScript project under `infrastructure/`
  - Define `AiProposalStack` with exactly 2 Lambda functions (`generate.py`, `proposals.py`), 2 DynamoDB tables (`proposals_draft`, `proposals_approved`), 1 S3 bucket, and 1 API Gateway
  - Configure CORS on all API Gateway routes (`allowOrigins: ALL_ORIGINS`, `allowMethods: ALL_METHODS`, `allowHeaders: ['Content-Type', 'Authorization']`)
  - Grant `generate.py` R/W on `proposals_draft` and R/W on S3; grant `proposals.py` R/W on `proposals_approved` and R on `proposals_draft`
  - Store Gemini API key as Lambda environment variable sourced from SSM Parameter Store
  - Configure Amplify Hosting resource for the React frontend
  - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7, 7.9_

  - [x]* 1.1 Write CDK assertion tests
    - Assert exactly 2 Lambda functions, 2 DynamoDB tables, 1 S3 bucket, 1 API Gateway
    - Assert IAM: `generate.py` has no `proposals_approved` write; `proposals.py` has no `proposals_draft` write
    - _Requirements: 7.1, 7.2, 7.5, 7.6_

- [x] 2. Implement `proposals.py` — presigned URL and proposal retrieval
  - Create `backend/proposals.py` Lambda handler with routing on `httpMethod` + `resource`
  - Implement `POST /upload-url`: generate UUID-based S3 key, return presigned PUT URL (5-minute expiry) and `s3Key`
  - Implement `GET /proposals`: scan `proposals_draft` (return `proposalId`, `status`, `createdAt`) and `proposals_approved` (return `proposalId`, `status="APPROVED"`, `approvedAt`); merge and return combined list; return empty list when none exist
  - Implement `GET /proposals/{id}`: get from `proposals_draft` first, then `proposals_approved`; return 404 if not found in either
  - Include CORS headers in all responses
  - _Requirements: 6.1, 6.2, 6.3, 6.4_

  - [x]* 2.1 Write unit tests for `proposals.py` retrieval paths
    - Test list merge logic, empty list case, 404 path for unknown ID
    - _Requirements: 6.1, 6.3, 6.4_

  - [x]* 2.2 Write property test for proposal list completeness (Property 12)
    - **Property 12: Proposal list is the complete union of both tables**
    - **Validates: Requirements 6.1, 6.4**

  - [x]* 2.3 Write property test for GET /{id} full record return (Property 13)
    - **Property 13: GET /proposals/{id} returns the full record for any existing ID**
    - **Validates: Requirements 6.2**

  - [x]* 2.4 Write property test for unknown proposalId 404 (Property 11 — GET path)
    - **Property 11: Unknown proposalId always returns 404**
    - **Validates: Requirements 6.3**

- [x] 3. Implement `proposals.py` — approve flow
  - Implement `POST /approve`: fetch draft from `proposals_draft` by `proposalId` (return 404 if missing), compute `editsMade` diff between `aiGeneratedSections` and `finalSections`, write record to `proposals_approved` with `proposalId`, `finalSections`, `approvedBy`, `approvedAt`, `editsMade`, `version`; return HTTP 200 with saved record
  - _Requirements: 5.1, 5.2, 5.3, 5.4, 5.5, 5.6_

  - [x]* 3.1 Write unit tests for approve flow
    - Test editsMade diff logic, successful approve, 404 on missing draft
    - _Requirements: 5.2, 5.3, 5.5_

  - [x]* 3.2 Write property test for approve round-trip (Property 9)
    - **Property 9: Approve round-trip — saved record matches returned record**
    - **Validates: Requirements 5.2, 5.6**

  - [x]* 3.3 Write property test for editsMade accuracy (Property 10)
    - **Property 10: editsMade accurately captures section diffs**
    - **Validates: Requirements 5.3**

  - [x]* 3.4 Write property test for unknown proposalId 404 on approve (Property 11 — POST path)
    - **Property 11: Unknown proposalId always returns 404 on POST /approve**
    - **Validates: Requirements 5.5**

- [x] 4. Checkpoint — Ensure all backend retrieval and approval tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 5. Implement `generate.py` — prompt construction and Gemini call
  - Create `backend/generate.py` Lambda handler
  - Implement input validation: require `surveyNotes` or at least one file key present
  - Fetch SOP content from S3 using provided `sopKeys`; inject verbatim into system prompt
  - Fetch reference proposal sections from `proposals_approved` if `referenceProposalId` provided
  - Build system prompt (SOP content injected) and user prompt (survey notes + base64 image parts + reference sections) using `google-genai` SDK multimodal parts
  - Call `gemini-2.5-flash` via `google-genai` SDK
  - Parse JSON response; validate all 6 required sections present (`Executive Summary`, `Scope of Work`, `Timeline`, `Budget Estimate`, `Methodology`, `Assumptions & Exclusions`)
  - On success: generate UUID `proposalId`, set `status=PENDING`, `version=1`, `createdAt=now()`, write to `proposals_draft`, return full record
  - On any error (Gemini exception, malformed JSON, missing sections): return HTTP 502 with descriptive message, write nothing to DynamoDB
  - Include CORS headers in all responses
  - _Requirements: 3.1, 3.2, 3.3, 3.4, 3.5, 3.6, 8.3, 8.4_

  - [x]* 5.1 Write unit tests for `generate.py`
    - Test prompt construction, JSON parsing, section validation, error path (mock Gemini to throw)
    - _Requirements: 3.1, 3.2, 3.5_

  - [x]* 5.2 Write property test for valid generation produces PENDING draft (Property 3)
    - **Property 3: Successful generation produces a valid PENDING draft record**
    - **Validates: Requirements 3.2, 3.3, 3.6**

  - [x]* 5.3 Write property test for Gemini errors never produce DynamoDB writes (Property 4)
    - **Property 4: Gemini errors never produce DynamoDB writes**
    - **Validates: Requirements 3.5, 9.3**

  - [x]* 5.4 Write property test for generate Lambda never writes to Approved Table (Property 5)
    - **Property 5: Generate Lambda never writes to Approved Table**
    - **Validates: Requirements 3.4, 5.4**

  - [x]* 5.5 Write property test for SOP content in system prompt (Property 6)
    - **Property 6: SOP content is always present in the Gemini system prompt**
    - **Validates: Requirements 8.4**

- [x] 6. Checkpoint — Ensure all backend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 7. Scaffold React + TypeScript frontend
  - Initialize React + TypeScript project under `frontend/` (Vite or CRA)
  - Install dependencies: React Router, a fetch/axios client
  - Set up routing: `/` → `Login.tsx`, `/dashboard` → `Dashboard.tsx`
  - Create `Navbar.tsx`: app title and logout button; logout clears auth session and redirects to `/`
  - Implement `Auth_Guard`: redirect unauthenticated users from `/dashboard` to `/`
  - _Requirements: 1.4, 1.5_

  - [x]* 7.1 Write property test for unauthenticated access redirects to Login (Property 15)
    - **Property 15: Unauthenticated access always redirects to Login**
    - **Validates: Requirements 1.4**

- [x] 8. Implement `Login.tsx`
  - Render centered card with email input, password input, and Sign In button
  - Phase 1: validate against hardcoded credentials; on success set auth session and navigate to `/dashboard`; on failure display inline error message and stay on page
  - _Requirements: 1.1, 1.2, 1.3_

  - [x]* 8.1 Write property test for invalid credentials always produce error without navigation (Property 14)
    - **Property 14: Invalid credentials always produce an error without navigation**
    - **Validates: Requirements 1.3**

- [x] 9. Implement `ProposalForm.tsx`
  - Multi-line textarea for survey notes (controlled input)
  - File input for photos (JPG, PNG only)
  - File input for reference documents (PDF, Word only)
  - File input for SOP documents (PDF, Word only) — distinct from reference docs
  - Dropdown to select a past proposal as reference (fetched from `GET /proposals`)
  - Client-side file type validation: reject disallowed types with error message
  - At-least-one-input guard: block submission if survey notes are blank/whitespace AND no files attached
  - Preserve all inputs on generation failure (controlled inputs)
  - Disable all inputs and show spinner on Generate Draft button while `isLoading` is true
  - On submit: request presigned URL per file via `POST /upload-url`, upload files directly to S3, then call `POST /generate` with S3 keys
  - _Requirements: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6, 2.7, 8.1, 8.2, 8.3, 9.2_

  - [x]* 9.1 Write unit tests for `ProposalForm`
    - Test file type validation, empty submission guard, input preservation on error
    - _Requirements: 2.5, 2.6, 9.2_

  - [x]* 9.2 Write property test for invalid file types always rejected (Property 1)
    - **Property 1: Invalid file types are always rejected**
    - **Validates: Requirements 2.5, 8.2**

  - [x]* 9.3 Write property test for empty form submission always blocked (Property 2)
    - **Property 2: Empty form submission is always blocked**
    - **Validates: Requirements 2.6**

  - [x]* 9.4 Write property test for generation failure preserves all form inputs (Property 16)
    - **Property 16: Generation failure preserves all form inputs**
    - **Validates: Requirements 9.1, 9.2, 9.4**

- [x] 10. Implement `DraftOutput.tsx`
  - Render each section with content and rationale visible
  - Inline edit control (textarea toggle) per section
  - Track edited vs original AI content in local state per section
  - Show Approve button only when a draft is present
  - Show user-friendly error message and retry button on generation failure (HTTP 502 or network error)
  - _Requirements: 4.1, 4.2, 4.3, 4.4, 9.1, 9.4_

  - [x]* 10.1 Write unit tests for `DraftOutput`
    - Test section rendering, inline edit state, approve button visibility, error + retry display
    - _Requirements: 4.1, 4.2, 4.4, 9.1_

  - [x]* 10.2 Write property test for DraftOutput renders all sections with edit controls (Property 7)
    - **Property 7: DraftOutput renders all sections with edit controls**
    - **Validates: Requirements 4.1, 4.2**

  - [x]* 10.3 Write property test for editing preserves original AI content (Property 8)
    - **Property 8: Editing a section preserves the original AI content**
    - **Validates: Requirements 4.3**

- [x] 11. Implement `Dashboard.tsx` and wire frontend together
  - Compose `ProposalForm` and `DraftOutput` side-by-side
  - Own draft state: pass draft data to `DraftOutput`, pass submit handler to `ProposalForm`
  - Handle approve action: send `POST /approve` with `proposalId`, edited `finalSections`, and `approvedBy`
  - Wire `Navbar` logout to clear session and redirect to `/`
  - Configure API base URL from environment variable
  - _Requirements: 1.5, 5.1_

- [x] 12. Checkpoint — Ensure all frontend tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [x] 13. Write README.md
  - Document AI approach: model (`gemini-2.5-flash`), prompt and orchestration strategy in `generate.py`
  - Document how SOP documents are incorporated into the Gemini prompt context
  - Document known limitations and planned next steps
  - Include step-by-step CDK deployment and Amplify hosting instructions
  - Add Governance section answering the 4 assessment questions:
    - AI Authority: which parts should never be fully automated and why (final pricing, legal scope, client commitments)
    - Explainability: how AI-generated scopes are made understandable (per-section rationale, source tracing)
    - Data Integrity: how AI outputs are prevented from polluting historical data (two-table separation, IAM boundaries)
    - Failure Modes: how the system behaves when AI extraction is incomplete or unavailable (HTTP 502, retry, inputs preserved)
  - _Requirements: 10.1, 10.2, 10.3, 10.4, 10.5_

- [x] 14. Final checkpoint — Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for a faster MVP
- Each task references specific requirements for traceability
- Property tests use **Hypothesis** (Python backend) and **fast-check** (TypeScript frontend)
- Unit tests complement property tests — both are needed for full coverage
- The draft record in `proposals_draft` is never deleted on approval — it serves as a permanent audit trail
