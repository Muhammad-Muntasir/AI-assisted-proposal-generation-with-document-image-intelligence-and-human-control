# Requirements Document

## Introduction

An AI-Assisted Proposal & Document Intelligence Platform that enables professionals to create project proposals with the help of Google Gemini AI. Users upload site notes, photos, and reference documents; the AI generates a structured draft proposal with per-section rationale. A human must review, optionally edit, and explicitly approve every draft before it becomes a final record. AI-generated data and human-approved truth are stored in separate DynamoDB tables and never mixed.

## Glossary

- **Platform**: The full AI-Assisted Proposal & Document Intelligence Platform, comprising frontend, backend, and infrastructure.
- **Dashboard**: The protected React page visible only to authenticated users, where proposals are created and managed.
- **Login_Page**: The public-facing React page where users authenticate before accessing the Dashboard.
- **Auth_Guard**: The frontend mechanism that prevents unauthenticated users from accessing the Dashboard.
- **ProposalForm**: The React component on the Dashboard that accepts survey notes, photos, documents, and past proposals as input.
- **DraftOutput**: The React component that displays the AI-generated draft sections and rationale, and allows inline editing.
- **Generate_Lambda**: The AWS Lambda function (`generate.py`) responsible for calling Gemini AI and saving a PENDING draft.
- **Proposals_Lambda**: The AWS Lambda function (`proposals.py`) responsible for approving drafts and retrieving proposal records.
- **Gemini_Client**: The Google Gemini 2.5 Flash API client used by Generate_Lambda to produce proposal content.
- **Draft_Table**: The DynamoDB table `proposals_draft` that stores AI-generated proposal drafts with status PENDING.
- **Approved_Table**: The DynamoDB table `proposals_approved` that stores human-approved final proposals.
- **API_Gateway**: The AWS API Gateway that routes HTTP requests from the frontend to the appropriate Lambda function.
- **S3_Bucket**: The AWS S3 bucket that stores uploaded photos and documents.
- **Cognito**: The AWS Cognito user pool used for authentication in Phase 2.
- **CDK_Stack**: The AWS CDK TypeScript stack that provisions all cloud infrastructure.

---

## Requirements

### Requirement 1: User Authentication

**User Story:** As a professional user, I want to log in with credentials, so that only authorized users can access the proposal platform.

#### Acceptance Criteria

1. THE Login_Page SHALL display a centered card with an email input, a password input, and a Sign In button.
2. WHEN a user submits valid Phase 1 hardcoded credentials, THE Auth_Guard SHALL grant access to the Dashboard.
3. WHEN a user submits invalid credentials, THE Login_Page SHALL display an error message without navigating away.
4. WHILE a user is not authenticated, THE Auth_Guard SHALL redirect any request to the Dashboard back to the Login_Page.
5. WHEN a user clicks the logout button in the navbar, THE Auth_Guard SHALL clear the session and redirect the user to the Login_Page.
6. WHERE Phase 2 Cognito integration is enabled, THE Auth_Guard SHALL authenticate users via Cognito with zero changes to the Login_Page UI.

---

### Requirement 2: File and Input Upload

**User Story:** As a professional user, I want to upload site notes, photos, and reference documents, so that the AI has the context it needs to generate a relevant proposal draft.

#### Acceptance Criteria

1. THE ProposalForm SHALL accept free-text survey notes via a multi-line text input.
2. THE ProposalForm SHALL accept photo uploads in JPG and PNG formats.
3. THE ProposalForm SHALL accept document uploads in PDF and Word formats.
4. THE ProposalForm SHALL provide a dropdown to select a past proposal as a reference.
5. WHEN a user selects a file that is not JPG, PNG, PDF, or Word format, THE ProposalForm SHALL display a validation error and reject the file.
6. WHEN a user clicks the Generate Draft button, THE ProposalForm SHALL require at least survey notes or one uploaded file to be present before submitting.
7. WHEN files are submitted, THE Platform SHALL upload them to S3_Bucket before invoking the Generate_Lambda.

---

### Requirement 3: AI Draft Generation

**User Story:** As a professional user, I want the AI to generate a structured proposal draft from my inputs, so that I have a high-quality starting point to review and refine.

#### Acceptance Criteria

1. WHEN a POST /generate request is received with survey notes and file references, THE Generate_Lambda SHALL invoke Gemini_Client using the `gemini-2.5-flash` model.
2. WHEN Gemini_Client returns a response, THE Generate_Lambda SHALL parse the response into named proposal sections, each with a content field and a rationale field.
3. WHEN the draft is parsed, THE Generate_Lambda SHALL save a new record to Draft_Table with status set to `PENDING`, a generated `proposalId`, `createdAt` timestamp, and `version` set to 1.
4. THE Generate_Lambda SHALL never write any record to Approved_Table.
5. WHEN Gemini_Client returns an error, THE Generate_Lambda SHALL return an HTTP 502 response with a descriptive error message and SHALL NOT save any record to Draft_Table.
6. WHEN the draft is saved, THE Generate_Lambda SHALL return the full draft record including `proposalId`, all sections, rationale, and status to the frontend.

---

### Requirement 4: Draft Review and Inline Editing

**User Story:** As a professional user, I want to review the AI-generated draft and edit individual sections, so that I can correct or refine the content before approving it.

#### Acceptance Criteria

1. WHEN a draft is returned from POST /generate, THE DraftOutput SHALL render each proposal section with its content and rationale visible.
2. THE DraftOutput SHALL provide an inline edit control for each section that allows the user to modify the section content directly.
3. WHILE a user is editing a section, THE DraftOutput SHALL preserve the original AI-generated content alongside the edited version until the draft is approved.
4. THE DraftOutput SHALL display the Approve button only after a draft has been successfully generated and is displayed.

---

### Requirement 5: Proposal Approval and Governance

**User Story:** As a professional user, I want to explicitly approve a reviewed draft, so that only human-verified content becomes a final proposal record.

#### Acceptance Criteria

1. WHEN a user clicks the Approve button, THE Dashboard SHALL send a POST /approve request containing the `proposalId` and the current (possibly edited) section content.
2. WHEN a POST /approve request is received, THE Proposals_Lambda SHALL write a new record to Approved_Table containing `proposalId`, `finalSections`, `approvedBy`, `approvedAt`, and `version`.
3. WHEN writing to Approved_Table, THE Proposals_Lambda SHALL populate the `editsMade` field with a record of which sections differ between the AI-generated draft and the submitted final content.
4. THE Proposals_Lambda SHALL never write AI-generated content directly to Approved_Table without a corresponding POST /approve request.
5. WHEN a POST /approve request is received for a `proposalId` that does not exist in Draft_Table, THE Proposals_Lambda SHALL return an HTTP 404 response.
6. WHEN a proposal is successfully approved, THE Proposals_Lambda SHALL return an HTTP 200 response with the saved Approved_Table record.

---

### Requirement 6: Proposal Retrieval

**User Story:** As a professional user, I want to view all proposals and open individual records, so that I can track the history of drafts and approved proposals.

#### Acceptance Criteria

1. WHEN a GET /proposals request is received, THE Proposals_Lambda SHALL return a list of all records from both Draft_Table and Approved_Table, each including `proposalId`, `status`, and `createdAt` or `approvedAt`.
2. WHEN a GET /proposals/{id} request is received with a valid `proposalId`, THE Proposals_Lambda SHALL return the full record from Draft_Table or Approved_Table matching that `proposalId`.
3. WHEN a GET /proposals/{id} request is received with a `proposalId` that does not exist in either table, THE Proposals_Lambda SHALL return an HTTP 404 response.
4. WHEN a GET /proposals request is received, THE Proposals_Lambda SHALL return an HTTP 200 response even when no proposals exist, with an empty list.

---

### Requirement 7: Infrastructure and Deployment

**User Story:** As a developer, I want all infrastructure defined as code and deployed via AWS CDK, so that the platform is reproducible, cost-controlled, and deployable to AWS.

#### Acceptance Criteria

1. THE CDK_Stack SHALL provision exactly two Lambda functions: Generate_Lambda and Proposals_Lambda.
2. THE CDK_Stack SHALL provision exactly two DynamoDB tables: Draft_Table and Approved_Table.
3. THE CDK_Stack SHALL provision one S3_Bucket for file uploads.
4. THE CDK_Stack SHALL provision one API_Gateway with routes: POST /generate, POST /approve, GET /proposals, and GET /proposals/{id}.
5. THE CDK_Stack SHALL grant Generate_Lambda read/write access to Draft_Table and read/write access to S3_Bucket.
6. THE CDK_Stack SHALL grant Proposals_Lambda read/write access to Approved_Table and read access to Draft_Table.
7. THE CDK_Stack SHALL store the Gemini API key as an environment variable on Generate_Lambda, sourced from a secure parameter or secret.
8. WHERE Phase 2 Cognito integration is enabled, THE CDK_Stack SHALL provision a Cognito user pool and attach it as an authorizer to API_Gateway with zero changes to existing Lambda function code.
9. THE CDK_Stack SHALL configure AWS Amplify Hosting to serve the compiled React frontend.

---

### Requirement 8: SOP Document Support

**User Story:** As a professional user, I want to upload SOP documents alongside my other inputs, so that the AI follows my company's writing guidelines when generating the proposal draft.

#### Acceptance Criteria

1. THE ProposalForm SHALL accept SOP document uploads in PDF and Word formats as a 5th input type, distinct from general reference documents.
2. WHEN a user selects a file for the SOP input that is not PDF or Word format, THE ProposalForm SHALL display a validation error and reject the file.
3. WHEN files are submitted, THE Platform SHALL upload SOP documents to S3_Bucket alongside photos and reference documents before invoking Generate_Lambda.
4. WHEN Generate_Lambda constructs the Gemini prompt, THE Generate_Lambda SHALL include the extracted SOP document content in the prompt context so that Gemini_Client applies the company writing guidelines when generating the draft.

---

### Requirement 9: Frontend Error Handling for AI Failures

**User Story:** As a professional user, I want clear feedback when proposal generation fails, so that I can understand what went wrong and retry without losing my inputs.

#### Acceptance Criteria

1. WHEN the POST /generate API returns an HTTP 502 response or a network failure occurs, THE DraftOutput SHALL display a user-friendly error message stating that generation failed.
2. WHEN generation fails, THE ProposalForm SHALL retain all user-entered inputs, including survey notes, uploaded files, and selected reference proposal, so the user can retry without re-entering data.
3. WHEN Gemini_Client is unavailable and Generate_Lambda returns an error, THE Platform SHALL NOT save any partial or empty draft record to Draft_Table.
4. WHEN generation fails, THE DraftOutput SHALL display a retry button that re-submits the original inputs to POST /generate.

---

### Requirement 10: README Documentation

**User Story:** As a developer, I want a README at the root of the repository, so that I can understand the AI approach, deployment steps, and known limitations without reading the full codebase.

#### Acceptance Criteria

1. THE Platform repository SHALL include a README.md file at the root level.
2. THE README SHALL document the AI approach including the model used (Gemini 2.5 Flash) and the prompt and orchestration strategy employed by Generate_Lambda.
3. THE README SHALL document how SOP documents are incorporated into the Gemini prompt context during draft generation.
4. THE README SHALL document known limitations of the platform and planned next steps.
5. THE README SHALL include step-by-step deployment instructions for provisioning infrastructure via CDK and hosting the frontend via Amplify.
