## 1. Corpus Configuration and Test Foundation

- [x] 1.1 Inspect the existing knowledge-base, Milvus, embedding, and Agentic RAG modules, document the extension points used by this change, and verify the inventory names the concrete symbols and files without proposing changes to MySQL, COS, or routing behavior.
- [x] 1.2 Add version-controlled configuration for corpus directories, pilot domains, parent/child chunk limits, overlap, review thresholds, and retrieval gates, and verify defaults match the design while environment-specific values remain configurable.
- [x] 1.3 Define the YAML public-source manifest schema with document identity, path or URL, source, technology, role tags, version, language, content type, license status, and target corpus version, and verify valid and invalid fixture manifests with schema tests.
- [x] 1.4 Create deterministic text, PDF, DOCX, and Markdown fixtures covering Q&A, headings, lists, code blocks, repeated content, malformed text, and scanned-PDF detection, and verify the fixtures are usable without external services.

## 2. Source Intake and Parsing

- [x] 2.1 Implement manifest loading and source validation so undeclared, missing, unsupported, or unlicensed sources cannot be published, and verify the behavior with failing-first unit tests.
- [x] 2.2 Implement pluggable PDF, DOCX, and Markdown parsers that preserve page or section location metadata, and verify representative fixture text and locations through parser tests.
- [x] 2.3 Detect empty, encrypted, scanned, or unreadable files and return per-document failure reasons without aborting the batch, and verify a mixed-success batch produces complete results.
- [x] 2.4 Implement deterministic normalization and cleaning for whitespace, headers, footers, line-break artifacts, control characters, and mojibake indicators without rewriting technical conclusions, and verify before/after fixture snapshots.
- [x] 2.5 Add a preview command that parses a declared batch and reports document length or pages, candidate knowledge units, chunks, duplicates, warnings, failures, and elapsed time without writing searchable Milvus entities, and verify Milvus entity counts remain unchanged.

## 3. Structure-Aware Parent and Child Chunking

- [x] 3.1 Implement rule-based recognition for complete interview Q&A, numbered questions, answers or explanations, chapter headings, lists, and code blocks, and verify complete Q&A units remain intact when under the configured limit.
- [x] 3.2 Add the optional low-confidence DeepSeek boundary classifier that may return only boundaries and content types, validate its structured output, cache results by content hash, and verify invalid or disabled model output falls back to deterministic rules.
- [x] 3.3 Implement parent knowledge-unit creation with section path, page range, structure confidence, content type, and original text, and verify every parsed block is either assigned once or reported as rejected.
- [x] 3.4 Implement child splitting for oversized parents with `RecursiveCharacterTextSplitter`, configurable separators and overlap, and start-index preservation, and verify child sizes, overlap bounds, and parent references.
- [x] 3.5 Build embedding text from technology labels, question or section title, section path, and child text while retaining unmodified evidence text separately, and verify embedding input and returned evidence have the intended distinct representations.
- [x] 3.6 Implement exact parent-context recovery by `parent_id`, `document_id`, and version metadata, and verify a child hit restores the correct Q&A without a secondary filename similarity search.

## 4. Metadata, Deduplication, and Idempotent Milvus Writes

- [x] 4.1 Define and validate the public chunk metadata contract, including stable IDs, corpus and document versions, hierarchy, roles, technology, source position, hashes, license, review, and publication status, and verify missing required metadata is rejected before embedding.
- [x] 4.2 Implement normalized SHA-256 document and parent hashes plus deterministic child IDs, and verify identical inputs produce identical IDs across repeated runs.
- [x] 4.3 Implement document-level exact deduplication and chunk-level exact or near-duplicate detection using normalized fingerprints and shingles or SimHash, and verify duplicated reposts and repeated headers are reported without quadratic all-corpus embedding comparison.
- [x] 4.4 Extend the existing Milvus public-ingestion path to use deterministic primary keys, dynamic metadata, and idempotent upsert with `auto_id=false`, and verify running the same batch twice creates zero duplicate searchable chunks.
- [x] 4.5 Verify the current `published` and role filters remain compatible with the extended metadata on an empty collection and a populated test collection.

## 5. Candidate Versions, Review, Publication, and Withdrawal

- [x] 5.1 Implement staged ingestion into an unpublished candidate `corpus_version`, with resumable per-stage artifacts and per-document status, and verify a failed document does not publish partial chunks or erase successful batch statistics.
- [x] 5.2 Implement automated quality checks for text completeness, structure confidence, missing answers, mojibake, duplication, source metadata, role tags, version conflicts, and license status, and verify each failure category is represented in tests and reports.
- [x] 5.3 Add CLI operations for preview, ingest, inspect, approve, publish, withdraw, retry, and statistics, and verify each command exposes help, returns non-zero on blocked operations, and produces machine-readable output.
- [x] 5.4 Implement explicit human approval records in version-controlled review artifacts without storing secrets or full sensitive source text, and verify unapproved candidates cannot pass the publication command.
- [x] 5.5 Implement compensated two-phase publication that validates the candidate before switching the active version and deactivating the prior version, and verify a simulated post-switch smoke-test failure restores the prior active filters.
- [x] 5.6 Implement version withdrawal with a recorded reason and immediate exclusion from default public retrieval while preserving audit metadata, and verify withdrawn chunks are absent from search but still inspectable administratively.
- [x] 5.7 Generate batch, review, publish, rollback, and withdrawal reports with counts, failures, duplicates, quality findings, actions, and timings, and verify reports redact API keys and do not embed complete third-party documents.

## 6. Pilot Corpus Intake

- [x] 6.1 Inventory the existing Redis, MySQL, and RAG/Milvus materials, record source and license status in the manifest, and verify unconfirmed third-party PDFs are marked local-evaluation-only.
- [x] 6.2 Register approved, version-specific official RAG, Milvus, and related framework sources needed for the pilot, and verify every URL, retrieval date, content version, and license decision is present before ingestion.
- [x] 6.3 Run preview ingestion for the three pilot domains, inspect low-confidence structures and duplicate candidates, correct manifest or parser rules, and verify the final preview has no unexplained fatal failures.
- [x] 6.4 Ingest the pilot into an isolated candidate version and verify document counts, parent counts, child counts, embedding counts, stable IDs, source traceability, and zero published chunks before approval.
- [x] 6.5 Register all 20 owner-authorized interview PDFs in a versioned full-corpus manifest with explicit technology, role, source, version, and `approved` license metadata, and verify every file in `知识库/` is declared exactly once.
- [x] 6.6 Preview and ingest all 20 PDFs into an isolated unpublished candidate version, inspect every per-document parse and structure report, and verify no authorized document is omitted, failed, or accidentally searchable before approval.

## 7. Retrieval Benchmark and Publication Gate

- [x] 7.1 Create a versioned Chinese golden query set with 30-60 Redis, MySQL, and RAG/Milvus interview queries covering definitions, principles, comparisons, troubleshooting, version differences, colloquial wording, and combined questions, and verify every query has role, target knowledge, expected source or parent, and graded relevance labels.
- [x] 7.2 Implement deterministic benchmark execution with fixed embedding model, filters, and Top-K parameters, and verify results include ranked chunks, scores, metadata, source positions, and latency for every query.
- [x] 7.3 Implement Hit@5, MRR@5, NDCG@5, knowledge coverage, duplicate-result rate, role-contamination rate, source-traceability rate, parent-recovery rate, and P50/P95 latency calculations, and verify metric formulas against hand-calculated fixtures.
- [x] 7.4 Implement answer-integrity checks that flag title-only, answerless, or incorrectly restored parent results, and verify oversized Q&A benchmark cases recover the intended question, answer, explanation, and source.
- [x] 7.5 Add human sampling artifacts for high-score, low-score, conflict, and boundary cases with consistent ratings for correctness, interview value, version relevance, and source quality, and verify sampled records link to exact queries and chunks.
- [x] 7.6 Implement configurable publication gates with pilot defaults from the design and recorded manual-override reasons, and verify any failed mandatory metric blocks publication while the current active version remains unchanged.
- [x] 7.7 Implement candidate-versus-current regression comparison and verify the report highlights ranking regressions, source changes, role contamination, coverage differences, and latency changes under identical benchmark parameters.
- [x] 7.8 Extend the versioned Chinese benchmark to cover every full-corpus technology family, run retrieval and parent-integrity evaluation against the full candidate, and verify the publication gate passes without regressing Redis or MySQL retrieval.

## 8. Agentic RAG and Quiz Regression Verification

- [x] 8.1 Publish a qualified pilot version in the test environment and verify ordinary authenticated public retrieval can find Redis, MySQL, and RAG/Milvus evidence through the existing `public_milvus_search` contract.
- [x] 8.2 Verify public retrieval results expose sufficient source and parent metadata for evidence scoring while the existing Tavily fallback and base-model fallback still behave according to the current Agentic RAG route.
- [x] 8.3 Verify personal-knowledge-base-only mode never consumes the new public corpus, and verify guest generation remains base-model-only.
- [x] 8.4 Run end-to-end generation for representative pilot topics and verify the first question, subsequent incremental questions, answers, explanations, and final report are grounded in the retrieved parent evidence without highly duplicated questions.
- [x] 8.5 Verify publishing, replacing, or withdrawing a public corpus version does not alter existing user documents, quiz sessions, progress records, generated images, avatars, reports, or MySQL business data.
- [x] 8.6 Approve and publish the qualified full-corpus version, then verify representative public searches and grounded incremental quiz generation across Java, frameworks, databases, middleware, computer fundamentals, and AI topics.

## 9. Automated and WeChat Developer Tools Validation

- [x] 9.1 Add backend TDD coverage for manifests, parsers, cleaning, structure recognition, splitting, hierarchy recovery, hashes, deduplication, Milvus writes, quality gates, publication compensation, withdrawal, and evaluation metrics, and verify the focused pytest suite passes.
- [x] 9.2 Run the complete backend pytest suite and verify existing authentication, user knowledge base, Agentic RAG, incremental quiz generation, progress, and report tests have no regressions.
- [x] 9.3 Run frontend TypeScript type checking and the WeChat mini-program production build, and verify no new warnings or build errors are introduced despite this change adding no user-facing page.
- [x] 9.4 Start the backend and built mini-program, then verify in WeChat Developer Tools that login, guest restrictions, topic generation, public-corpus generation, personal-document-only generation, incremental answering, unfinished-practice resume/delete, report review, and profile navigation remain usable.
- [ ] 9.5 Run retrieval latency and filter regression tests against the target Milvus Standalone deployment, record P50/P95 and parent-expansion latency, and verify the release report meets the configured performance gate before cloud deployment.
- [x] 9.6 Produce an operator runbook for adding sources, confirming licenses, previewing, reviewing, evaluating, publishing, replacing, withdrawing, rolling back, and diagnosing failures, and verify a clean-environment dry run can follow it without undocumented steps.
