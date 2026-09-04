# Milvus Runtime Smoke Test

- Endpoint: `http://127.0.0.1:8000`
- Health: `GET /api/v1/health` returned HTTP 200.
- Milvus Standalone: server `2.5.16`; public/private native collections loaded and healthy.
- Authentication boundary: `GET /api/v1/user/profile` without a token returned HTTP 401.
- Real generation request: guest task for `RAG技术`, role `ai`, difficulty `easy`, six questions.
- Task lifecycle: `queued` -> `generating` (`3/6`, `4/6`, `5/6`) -> `completed` (`6/6`).
- Polling interval: 6 seconds.
- Observed elapsed time: approximately 33 seconds including the initial request and polling.
- No API keys, tokens, or document contents were written to the log.

The request was issued with an UTF-8 JSON body. Windows `curl.exe` with an unescaped inline JSON string produced a client-side body parsing error and is not representative of the API behavior.
