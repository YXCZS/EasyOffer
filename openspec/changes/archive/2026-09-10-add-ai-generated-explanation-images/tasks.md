## 1. Domain Model And Configuration

- [x] 1.1 Add the optional `QuestionVisualization` domain model and backward-compatible question serialization fields, then verify existing quiz model tests pass for missing, pending, ready, and failed visualization values.
- [x] 1.2 Add image generation, COS, asset limits, timeout, concurrency, retry, 512x512 output, and feature-toggle settings with safe disabled defaults, then verify settings load without credentials and do not prevent application startup.
- [x] 1.3 Add `quiz_visual_assets` schema initialization and indexes with a rollback note, then verify the migration is idempotent and existing quiz/task rows remain readable.

## 2. AI Prompt And Image Provider

- [x] 2.1 Extend one-shot and incremental DeepSeek question prompts to return a bounded visualization decision, image mode/type, minimal image prompt, and alt text while preserving all existing question fields; verify parser tests cover enabled and disabled responses.
- [x] 2.2 Implement the configurable Bailian image client for the selected Qwen Image model, supporting temporary URL and base64 responses, request timeouts, response validation, and bounded logging; verify mocked provider tests cover both response forms and malformed responses.
- [x] 2.3 Implement prompt hashing and a visualization policy that caps images per quiz, filters unsafe or oversized prompts, and reuses pending/ready assets; verify duplicate submissions do not invoke the provider twice.

## 3. COS Persistence And Background Processing

- [x] 3.1 Implement the Tencent COS adapter using `cos-python-sdk-v5` with environment-only credentials, object-key generation, MIME metadata, public-read object ACL, stable public URL generation, and a private signed-URL fallback; verify mocked SDK tests cover upload success, client errors, URL generation, and both access modes.
- [x] 3.2 Implement the asset repository and state transitions `pending -> generating -> uploading -> ready|failed`, including ownership fields, retry count, bounded error messages, and idempotent uniqueness; verify repository tests cover concurrent claims and terminal states.
- [x] 3.3 Implement background visual-asset processing triggered after a valid question is persisted, including provider download/base64 decode, size/type checks, COS upload, retry, and failure downgrade; verify a provider or COS failure leaves the question task usable and marks only the asset failed.
- [x] 3.4 Integrate asset status and public image URL hydration into one-shot and incremental task snapshots without delaying the first question; verify an incremental test receives a text-complete question while its asset is pending and later observes ready status.

## 4. Frontend Display And Compatibility

- [x] 4.1 Extend TypeScript question types and snapshot merging to preserve visualization fields through one-shot, incremental, resume, and history flows; verify `npm run typecheck` and existing session tests pass with legacy questions.
- [x] 4.2 Add answer-feedback UI for ready images, pending status, alt text, and failed fallback using Taro `Image` with proportional sizing; verify image loading errors keep text explanation and next-question controls usable.
- [x] 4.3 Add the “生成图片” switch to quiz settings, default it off, and include it in both one-shot and incremental requests; verify disabled requests make no image task.
- [x] 4.4 Extend history detail data and UI to render ready question images and text-only fallback; verify legacy history payloads load without errors.
- [x] 4.5 Match existing EasyOffer visual styles and responsive spacing without changing the “答题” and “我的” tab bar; verify the WeChat build contains no browser-only Mermaid dependency.

## 5. Backend Tests And Integration Verification

- [x] 5.1 Add TDD coverage for visualization schema validation, prompt policy, image client, COS adapter, repository idempotency, retry/failure downgrade, and URL access behavior; verify `pytest -q` passes.
- [x] 5.2 Add integration tests for one-shot and incremental generation with mocked DeepSeek, provider, COS, and polling, including disabled credentials and legacy question payloads; verify core question, answer, score, and report paths are unchanged.
- [x] 5.3 Run `python -m compileall -q app`, `npm run typecheck`, and `npm run build:weapp`; record outputs and confirm no regression in existing core tests.

## 6. Environment And WeChat Verification

- [x] 6.1 Document required `.env` values for Bailian and COS without committing secrets, then verify missing optional image credentials leave text-only generation operational.
- [x] 6.2 Start the backend and frontend build, import the generated `dist` into WeChat Developer Tools, and verify a normal question can be generated, answered, and reviewed while an asset transitions through pending/ready or failed fallback.
- [x] 6.3 Verify the configured public COS URL is anonymously readable, private mode still produces signed URLs, and temporary provider URLs or credentials never appear in frontend payloads or logs.
