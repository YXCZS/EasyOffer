## 1. Dependencies and Configuration

- [x] 1.1 Add version-compatible `langgraph`, `langchain-milvus`, and `pymilvus` dependencies without removing existing Tavily/Chroma packages; verify backend dependency installation and import smoke test succeed
- [x] 1.2 Add Milvus URI, token, collection names, vector dimension, retrieval thresholds, loop limits, tool budgets, and timeouts to settings and `.env.example`; verify settings load with missing optional values and never logs secrets
- [x] 1.3 Add Milvus Standalone health check and collection/index initialization command for public and private collections; verify an empty local Milvus can be initialized idempotently

## 2. Milvus Storage and Ingestion

- [x] 2.1 Implement a vector-store adapter for public and private Milvus collections with dense-vector upsert, delete, metadata filtering, and similarity search; verify unit tests cover role/status filters and owner/document isolation
- [x] 2.2 Preserve the existing MySQL knowledge document repository and processing states while routing processed user chunks to private Milvus; verify existing knowledge API tests still pass and no MySQL schema diff is generated
- [x] 2.3 Implement public corpus ingestion for supplied and approved sources: parse, clean, deduplicate, chunk, embed, attach role/technology/version metadata, and write unpublished records; verify a fixture document produces deterministic hashes and chunk metadata
- [x] 2.4 Add public corpus quality-review and publish/unpublish commands with source and version metadata; verify unpublished or failed chunks are excluded from retrieval
- [x] 2.5 Implement Chroma-to-Milvus migration and verification utilities with dry-run, counts, content-hash comparison, and resumable batches; verify a fixture migration reports matching chunk counts and can be rerun safely

## 3. Topic Preparation and Routing Graph

- [x] 3.1 Separate deterministic topic normalization from query expansion and expose a typed preparation result containing canonical topic, URL flag, subtopics, and mode; verify tests preserve technical identifiers and remove conversational prefixes
- [x] 3.2 Make topic-scope judgement run before query expansion or external retrieval and return a user-facing rejection for unsupported topics; verify unsupported-topic tests assert zero Milvus/Tavily calls and no partial quiz
- [x] 3.3 Implement mandatory query expansion for supported keyword topics, with exact canonical-topic anchoring and bounded variants; verify tests cover multi-part topics, topic drift prevention, URL bypass, and private-mode query-only expansion
- [x] 3.4 Build the LangGraph StateGraph with explicit state, route controller, ToolNode integrations, evidence grader, query rewrite node, and finish/fallback edges; verify graph compilation and deterministic routing tests pass without network access
- [x] 3.5 Replace placeholder routing tools with real public Milvus, private Milvus, Tavily Search, and Tavily Extract tool adapters; verify mocked tool calls return normalized evidence and are recorded in graph state
- [x] 3.6 Enforce immutable policy guards for guest, URL, normal authenticated, and personal-only modes before Agent execution; verify adversarial Agent decisions cannot access a forbidden tool or user/document scope
- [x] 3.7 Implement evidence grading, deduplication, source ranking, version-conflict tracking, and query-rewrite loops with maximum rounds, calls, elapsed time, and context size; verify tests stop on sufficient evidence, rewrite on poor evidence, and terminate at budget
- [x] 3.8 Return the existing `EvidenceContext` contract plus route, query plan, tool calls, confidence, coverage, conflict, candidate/filtered counts, and fallback metadata; verify downstream question-generation tests consume both grounded and fallback contexts

## 4. Quiz Generation Integration

- [x] 4.1 Refactor incremental preparation to execute normalization, scope judgement, query expansion, and Agentic RAG in the specified order instead of starting evidence retrieval concurrently; verify task traces show no retrieval before a supported judgement
- [x] 4.2 Integrate minimum-evidence release with incremental generation so question one persists as soon as usable evidence is available while later research and questions continue in the background; verify generation-task snapshots expose question one before completion
- [x] 4.3 Preserve base-model fallback semantics for Tavily/Milvus/Agent failures and personal-only insufficiency without crossing data-source boundaries; verify failure-injection tests complete a usable quiz and record diagnostic reasons
- [x] 4.4 Preserve image-generation scheduling, answer progress, report generation, and existing task polling contracts; verify existing incremental quiz, progress-conflict, visualization, and report tests pass

## 5. Frontend Data-Source Selection

- [x] 5.1 Add the 鈥滀娇鐢ㄤ釜浜虹煡璇嗗簱鈥?selection state to the existing answer-home settings and include it in generation-task requests while preserving document-entry start behavior; verify Taro typecheck and request payload tests
- [x] 5.2 Render source status and fallback explanations from evidence metadata without exposing internal prompts or secrets; verify normal, personal-only, guest, URL, and fallback snapshots render the expected Chinese labels
- [x] 5.3 Keep the existing generating, incremental answer, resume, image, and report pages compatible with the new task snapshots; verify `npm run typecheck` and `npm run build:weapp`

## 6. Migration, Observability, and Operations

- [x] 6.1 Add structured logs and metrics for route, tool calls, evidence confidence, loop rounds, latency, fallback reason, and first-question latency with topic/content redaction; verify logs contain no document text or credentials
- [x] 6.2 Run Chroma/Milvus shadow retrieval comparisons for representative public and private queries and define the cutover threshold; verify comparison output includes recall agreement, latency, and mismatched metadata cases
- [x] 6.3 Add feature flags for Milvus read path, Agentic RAG graph, and Chroma fallback; verify disabling each flag restores the documented legacy path without changing MySQL or COS data
- [x] 6.4 Document Milvus Standalone backup, restore, upgrade-to-Distributed considerations, and rollback procedure; verify a clean environment can follow the documented initialization and rollback commands

## 7. TDD and End-to-End Verification

- [x] 7.1 Add unit tests for normalization, scope judgement, query expansion validation, policy guards, and route decisions; verify the focused pytest suite passes
- [x] 7.2 Add mocked LangGraph node/tool tests for public Milvus, private Milvus, Tavily Search, Tavily Extract, evidence grading, rewrite loops, and budget termination; verify no real network dependency is required
- [x] 7.3 Add integration tests for public ingestion, private document upload, owner isolation, personal-only generation, normal authenticated generation, URL extraction, guest fallback, and unsupported-topic rejection; verify the full backend pytest suite passes
- [x] 7.4 Run backend compile/lint and full pytest, then frontend typecheck and WeChat build; record command output and any environment prerequisites
- [x] 7.5 In WeChat Developer Tools, manually verify normal public-knowledge generation, personal-only generation, guest generation, URL input, first-question release, continued background generation, answer progress save/resume, report generation, and image fallback; record any tool/IDE limitation instead of marking it passed


