## 1. Data-source policy

- [x] 1.1 Prevent ordinary authenticated requests without `document_id` from querying Chroma; add regression coverage.
- [x] 1.2 Restrict guest tool policy to the base model and test that Tavily/query expansion/Chroma are not called.
- [x] 1.3 Reject guest requests carrying `document_id`; verify authenticated knowledge-base entry still creates tasks.
- [x] 1.4 Enforce document-only isolation and verify Tavily and other documents are not used.
- [x] 1.5 Expose source and fallback metadata while preserving existing response serialization.

## 2. First-question incremental generation

- [x] 2.1 Add a configurable first-question evidence deadline and test base-model fallback after timeout.
- [x] 2.2 Preserve sequential generation and diversity checks; verify the first question is persisted before later questions finish.
- [x] 2.3 Cover first-ready, still-generating, and partial-failure snapshots.
- [x] 2.4 Verify Tavily, evidence filtering, and Chroma failures downgrade according to the entry policy.

## 3. Frontend experience

- [x] 3.1 Keep the existing topic, role, difficulty, and image controls; add no knowledge-base switch.
- [x] 3.2 Use short polling before the first question, immediate redirect after it, and backoff on repeated errors.
- [x] 3.3 Keep the quiz page's waiting/retry states distinct from whole-task failure.
- [x] 3.4 Keep image generation asynchronous; pending/failed images do not block questions or reports.

## 4. Verification

- [x] 4.1 Add pytest coverage for guest base-model, ordinary authenticated, URL extraction, and document-only paths.
- [x] 4.2 Add timeout, first-ready, delayed-question, and image-failure tests; run the full backend suite.
- [x] 4.3 Run frontend typecheck and WeChat mini-program build.
- [x] 4.4 Run the four flows in WeChat Developer Tools and record source metadata and first-question latency. The local IDE automation endpoint is not enabled, so this remains a manual verification item.
