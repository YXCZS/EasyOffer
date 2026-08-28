## 1. Backend Data Model And Contracts

- [x] 1.1 Add the `quiz_generation_tasks` MySQL schema, indexes, status fields, JSON payload fields, version and expiry columns; verify a fresh database initializes it and existing quiz/progress tables remain unchanged.
- [x] 1.2 Add Pydantic request/response models for task creation, atomic snapshots, generated question drafts and task progress; verify valid/invalid payloads with model tests.
- [x] 1.3 Add repository methods for create, versioned snapshot update, progress update, retry, completion and expiry; verify transaction rollback and optimistic-concurrency tests.

## 2. Incremental Generation Service

- [x] 2.1 Refactor the DeepSeek generator behind an internal single-question generation method that reuses one evidence context and validates each question; verify unique, schema-valid questions with a fake model provider.
- [x] 2.2 Implement the incremental generation service lifecycle (`queued` -> `generating` -> `completed`/`failed`) with per-question retry limits and task-level timeout; verify first-question publication, ordered append and partial failure behavior.
- [x] 2.3 Implement task finalization that assembles a complete six-question Quiz and invokes existing quiz/progress persistence exactly once; verify idempotent completion and report compatibility.
- [x] 2.4 Add FastAPI task endpoints for create, snapshot, answer-progress update and retry, including authenticated document ownership checks and anonymous task TTL rules; verify success, unauthorized, not-ready document, unknown task and conflict responses.
- [x] 2.5 Register background execution and startup recovery for interrupted tasks; verify stale generating tasks become recoverable failures without deleting already generated questions.
- [x] 2.6 Keep `/api/v1/quiz/generate` on its existing synchronous path and add compatibility tests proving request/response behavior is unchanged.

## 3. Frontend Incremental Session

- [x] 3.1 Add task API clients and typed draft/snapshot models in `frontend/src/services/api.ts`; verify TypeScript typecheck and correct request payloads.
- [x] 3.2 Extend the session store with optional task ID, generated-question draft, task version and task progress persistence while preserving legacy session restoration; verify old and new storage shapes restore correctly.
- [x] 3.3 Replace the generation page's single long request with task creation plus lifecycle polling; verify it redirects after the first question, shows generated count, stops polling on completion/failure, and supports retry.
- [x] 3.4 Update the quiz page to merge newly available questions, pause at an unavailable next question, persist answers through the task-progress endpoint, and switch to the existing progress endpoint after finalization; verify no navigation to a missing question.
- [x] 3.5 Preserve existing report, history, bottom navigation and knowledge-document start-answering flows after an incremental task completes; verify the complete Quiz shape reaches the report page.

## 4. Automated Verification

- [x] 4.1 Add backend unit tests for task state transitions, atomic snapshots, ordering, retry limits, partial failure, expiry and cross-user isolation; verify with `python -m pytest -q`.
- [x] 4.2 Add backend integration tests for first-question latency semantics using a delayed fake generator and for legacy endpoint compatibility; verify all existing backend tests still pass.
- [x] 4.3 Add frontend tests or deterministic store-level checks for polling merge, waiting state, resume and finalization; verify with `npm run typecheck`.
- [x] 4.4 Build the WeChat mini-program bundle and verify `npm run build:weapp` completes without compilation errors.

## 5. WeChat Developer Tool Validation

- [ ] 5.1 Import the rebuilt `frontend/dist` bundle and verify a normal topic reaches the answer page after the first question while later questions appear without page reload.
- [ ] 5.2 Verify delayed generation, failed-question retry, leaving/resuming, knowledge-base-only generation and final report generation in the WeChat developer tool; record any AppID or IDE automation limitation separately.

> 5.1/5.2 remain pending: the local WeChat developer tool automation reached the IDE but failed while fetching AppID detailed information, and its automation endpoint then reported `Port is not provided`. The rebuilt bundle and backend API were verified independently; these two manual IDE scenarios require a working AppID/IDE session.
