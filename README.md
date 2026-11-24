# RAG Knowledge Assistant

An enterprise-ready, full-stack **Retrieval-Augmented Generation (RAG)** platform built from first principles in Python (FastAPI) and TypeScript (React 18 + Vite). 

Designed without opaque orchestration frameworks (no LangChain, LlamaIndex, or LangGraph), this project exposes every layer of modern enterprise RAG: deterministic chunking, semantic vector search with PostgreSQL and pgvector, full-text lexical search, Reciprocal Rank Fusion (RRF), cross-encoder reranking, multi-tenant workspace isolation, Role-Based Access Control (RBAC), immutable audit logging, distributed query tracing, and automated anomaly alerting.

---

## 1. Project Introduction

The **RAG Knowledge Assistant** is a self-contained, multi-tenant document intelligence service. It enables teams to upload complex PDF documents, extract and chunk text with strict document boundaries, compute vector embeddings via Google Gemini (`gemini-embedding-2`), and converse grounded strictly in their private documents via Gemini LLMs (`gemini-2.0-flash` or `gemini-3.7-flash`).

Unlike standard toy implementations, this repository implements a complete production foundation:
- **Zero-framework RAG engine**: Complete transparency over embeddings, SQL queries, fusion math, and prompt construction.
- **Enterprise governance**: JWT authentication (Argon2id hashing, rotating refresh tokens), multi-tier tenancy (Organizations and Workspaces), granular Document Access Control Lists (ACLs), and append-only audit trails.
- **Production observability**: End-to-end query tracing (LLM latency, TTFT, retrieval time, token usage) with automated anomaly detection and alerting rules.
- **Rigorous evaluation suite**: Offline deterministic regression testing and LLM-as-a-judge generation evaluation harness.

---

## 2. Problem Statement

Most real-world deployments of Large Language Models encounter three fundamental failure modes:
1. **Hallucination & Stale Data**: Foundation models answer authoritatively even when information is missing, obsolete, or incorrect.
2. **Framework Lock-in & Opacity**: Libraries like LangChain or LlamaIndex wrap basic SQL and API calls in multiple layers of abstraction, making debugging prompt injection, ranking anomalies, and latency spikes difficult.
3. **Missing Production Governance**: Prototype RAG projects rarely address tenant isolation, per-document access control, credential revocation, auditability, or operational latency monitoring.

**RAG Knowledge Assistant** addresses these problems by providing an auditable, deterministic RAG architecture where retrieval, security, and observability are engineered directly into the application stack.

---

## 3. Key Features

- **Document Ingestion & Validation**: Multi-layer PDF validation (file extension, MIME type, `%PDF` magic bytes, encryption check, and stream parseability).
- **Dual Chunking Strategies**: Configurable page-bounded `fixed_word_window` (default 700/100) and syntax-aware `recursive` paragraph/sentence packing.
- **Gemini Embeddings**: Vector representations generated using `gemini-embedding-2` (768-dimensional output) with explicit task types (`RETRIEVAL_DOCUMENT` vs. `RETRIEVAL_QUERY`).
- **Dense Vector Search**: Exact cosine similarity powered by PostgreSQL `pgvector` indexing with strict similarity thresholds.
- **Hybrid Retrieval & RRF**: Dual-branch candidate retrieval combining dense semantic similarity and PostgreSQL Full-Text Search (`tsvector`/`tsquery` + identifier matching) blended using Reciprocal Rank Fusion.
- **Stage 4 Cross-Encoder Reranking**: Opt-in local CPU reranking powered by `sentence-transformers` and `BAAI/bge-reranker-v2-m3`.
- **SQL-Level Metadata Filtering**: Pre-filtering by category, source, tags, date range, page range, and document IDs prior to ranking.
- **Strict Grounding & Prompt Defense**: Structured prompt engineering treating document passages and conversation history as untrusted data; deterministic refusal when retrieval returns empty context.
- **Streaming Assistant (SSE)**: Real-time token streaming using Server-Sent Events with structured event typing (`start`, `token`, `sources`, `done`, `error`).
- **Conversational Memory**: PostgreSQL-persisted multi-turn dialogue with configurable sliding-window prompt injection.
- **Multi-Tenant Architecture**: Hierarchical Organization & Workspace structure with role-based permissions (`OWNER`, `ADMIN`, `MEMBER`, `WORKSPACE_ADMIN`, `CONTRIBUTOR`, `VIEWER`).
- **Document ACLs**: Explicit per-user and per-workspace permission grants on individual documents.
- **Audit Logging**: Immutable, tamper-evident action logging for all security, authentication, and document lifecycle events.
- **Query Tracing & Observability**: Granular trace recording capturing retrieval durations, fusion timing, LLM latency, token counts, and cold-start events.
- **Operational Alerting**: Rule-based evaluation engine and anomaly detector monitoring error spikes, P95 latency breaches, and provider failures.
- **Evaluation Harness**: Automated CLI scoring Hit@K, MRR, NDCG, and generation faithfulness against frozen test suites.

---

## 4. Technology Stack

### Backend
| Component | Technology | Version | Purpose |
|---|---|---|---|
| Runtime | Python | 3.12 | Modern asynchronous runtime |
| Web Framework | FastAPI | 0.115.8 | High-performance ASGI REST and SSE endpoints |
| ASGI Server | Uvicorn | 0.34.0 | Production asynchronous server |
| ORM | SQLAlchemy | 2.0.38 | Type-safe SQL modeling and repository queries |
| DB Driver | Psycopg 3 | 3.2.5 | High-efficiency native PostgreSQL driver |
| Migrations | Alembic | 1.14.1 | Incremental, reversible database schema versioning |
| Config & Validation | Pydantic / Settings | 2.7.1 | Strict type validation and environment parsing |
| AI Client | google-genai | 2.21.0 | Official Google GenAI SDK for Gemini generation & embeddings |
| PDF Processing | pypdf | 6.1.1 | PDF extraction and document structure parsing |
| Reranker | sentence-transformers | 3.4.1 | Local CPU cross-encoder model inference |
| Authentication | PyJWT & argon2-cffi | 2.15.1 / 25.1.0 | Short-lived JWTs and OWASP-compliant password hashing |
| Test Suite | pytest | 8.3.4 | Automated unit, integration, and E2E testing |

### Frontend
| Component | Technology | Version | Purpose |
|---|---|---|---|
| UI Framework | React | 18.3.1 | Declarative component hierarchy |
| Tooling & Bundler | Vite | 6.2.2 | Fast HMR dev server and optimized production packaging |
| Language | TypeScript | ~5.7.3 | End-to-end static typing |
| Styling | Tailwind CSS | 3.4.17 | Utility-first responsive design |
| Component Primitives | Material UI | 6.4.8 | Targeted UI components (Drawers, Tooltips) |

### Infrastructure & Database
| Component | Technology | Version | Purpose |
|---|---|---|---|
| Database Engine | PostgreSQL | 16 | Relational data, full-text search, and multi-tenant schema |
| Vector Engine | pgvector | 0.7.x (pg16) | High-performance vector storage and distance calculations |
| Containerization | Docker & Docker Compose | v2 | Reproducible container orchestration |

---

## 5. System Architecture

```mermaid
flowchart TD
    subgraph Client ["Frontend (React 18 + Vite)"]
        UI["User Interface Dashboard / Assistant"]
        ClientAPI["API Client (fetch / SSE)"]
        UI --> ClientAPI
    end

    subgraph Gateway ["FastAPI Gateway & Security Layer"]
        CORS["CORS & Request Context"]
        AuthMiddleware["JWT Auth & Workspace Context"]
        TracingMiddleware["Tracing Middleware"]
        CORS --> TracingMiddleware --> AuthMiddleware
    end

    subgraph Services ["Application Service Layer"]
        DocService["DocumentService"]
        RetrievalService["RetrievalService (Dense / Hybrid)"]
        RerankService["RerankService (CrossEncoder)"]
        RAGService["RagService"]
        AuditService["AuditService"]
        TraceService["TracingService"]
        AlertService["AlertService"]
    end

    subgraph Storage ["Data Persistence Layer"]
        PG[("PostgreSQL 16 + pgvector")]
        DocStore[("Local File Storage /storage/documents")]
    end

    subgraph External ["External Provider"]
        GeminiAPI["Google Gemini API (Embeddings & LLM)"]
    end

    ClientAPI --> Gateway
    AuthMiddleware --> Services
    DocService --> DocStore
    DocService --> PG
    RetrievalService --> PG
    RerankService -.-> RetrievalService
    RAGService --> RetrievalService
    RAGService --> GeminiAPI
    DocService --> GeminiAPI
    Services --> AuditService --> PG
    Services --> TraceService --> PG
    TraceService --> AlertService --> PG
```

---

## 6. RAG Pipeline Explanation

```mermaid
sequenceDiagram
    autonumber
    actor User as Client
    participant API as FastAPI Router
    participant Tenant as Workspace & ACL Guard
    participant RAG as RAG Service
    participant Gemini as Gemini API
    participant DB as PostgreSQL (pgvector + FTS)
    participant Tracer as Tracing Service

    User->>API: POST /api/v1/chat/stream {question, conversation_id, filters}
    API->>Tenant: Verify Workspace & Document Permissions
    Tenant-->>API: Authorized
    API->>Tracer: Start Query Trace
    API->>RAG: Process Question(question, history, filters)
    
    RAG->>Gemini: Embed Question (task_type=RETRIEVAL_QUERY)
    Gemini-->>RAG: 768-dim query vector
    
    par Dense Branch
        RAG->>DB: Cosine Distance Search (<=>) [threshold >= 0.7]
        DB-->>RAG: Top-K Dense Candidates
    and Lexical Branch (Optional Hybrid)
        RAG->>DB: Full-Text plainto_tsquery + Identifier ILIKE
        DB-->>RAG: Top-K Lexical Candidates
    end
    
    RAG->>RAG: Reciprocal Rank Fusion (RRF) & Optional Reranking
    
    alt Retrieval Empty
        RAG-->>API: Controlled No-Context Refusal
        API-->>User: SSE: token ("Information not found in uploaded documents")
    else Context Retrieved
        RAG->>RAG: Construct Grounded System Prompt
        RAG->>Gemini: Stream Generation (Prompt + History + Passages)
        loop Token Stream
            Gemini-->>RAG: Text Chunk
            RAG-->>API: Yield Token
            API-->>User: SSE event: token
        end
        API-->>User: SSE event: sources (Citations)
    end
    
    API->>DB: Persist User & Assistant Messages
    API->>Tracer: Complete Trace (Latency, Token Metrics)
    API-->>User: SSE event: done
```

---

## 7. Document Ingestion Workflow

```mermaid
flowchart LR
    A["PDF Upload"] --> B["Binary Validation (%PDF, MIME, Size)"]
    B --> C["pypdf Page Extraction"]
    C --> D["Page-Bounded Chunking"]
    D --> E["Gemini Batch Embedding (RETRIEVAL_DOCUMENT)"]
    E --> F["PostgreSQL Transaction (documents + document_chunks)"]
    F --> G["Persist original.pdf in storage/"]
    G --> H["Status: COMPLETED"]
```

1. **Upload & Preflight**: Incoming multipart requests are validated for size (`MAX_UPLOAD_SIZE_MB`), MIME type (`application/pdf`), and magic bytes (`%PDF`).
2. **Text Extraction**: `pypdf.PdfReader` parses pages sequentially. Empty or unextractable scanned pages are recorded without failing the valid pages.
3. **Chunking**: Text is split strictly within page boundaries. Chunks never bridge across separate PDF pages.
4. **Vector Embedding**: Document chunks are vectorized in batches using Gemini's `RETRIEVAL_DOCUMENT` task type.
5. **Atomic Commit**: Document records, chunk texts, and vector embeddings are written to PostgreSQL inside an atomic database transaction.
6. **File Storage**: The validated source file is saved to disk under `storage/documents/<document-id>/original.pdf`.

---

## 8. Chunking and Embedding Process

### Chunking Strategies
Configurable via `CHUNKING_STRATEGY`:

- **`fixed_word_window` (Production Default)**:
  - Splits text into sequential windows of `CHUNK_SIZE` words (default: `700`).
  - Advances with a `CHUNK_OVERLAP` word step (default: `100`).
  - Preserves exact page numbers for accurate citation tracking.
- **`recursive`**:
  - Recursively splits text along structural separators: paragraph breaks (`\n\s*\n`), sentence boundaries (`(?<=[.!?])\s+`), and word boundaries.
  - Packs textual units greedily into `CHUNK_SIZE` allocations while enforcing `CHUNK_OVERLAP`.

### Embedding Specifications
- **Provider**: Google Gemini via `google-genai` SDK.
- **Model**: `gemini-embedding-2`.
- **Output Dimensionality**: `768` (must match database column `vector(768)`). Supported options: `768`, `1536`, `3072`.
- **Task Types**:
  - `EmbeddingTask.DOCUMENT` (`RETRIEVAL_DOCUMENT`): Tailored for dense document indexing.
  - `EmbeddingTask.QUERY` (`RETRIEVAL_QUERY`): Optimized for user query intent.

---

## 9. Hybrid Retrieval (Dense + Lexical)

When `RETRIEVAL_MODE=hybrid` is enabled, the backend performs multi-channel retrieval:

1. **Dense Semantic Branch**:
   - Computes cosine distance using pgvector `<=>`.
   - Exposes cosine similarity: `similarity = 1 - cosine_distance`.
   - Filters out chunks below `RAG_SIMILARITY_THRESHOLD` (default: `0.7`).
2. **Lexical Full-Text Search Branch**:
   - Leverages a generated PostgreSQL `TSVECTOR` column (`content_tsv`) indexed with GIN.
   - Parses the query using `plainto_tsquery('simple', :question)` to prevent search syntax injection.
   - Performs parameterized `ILIKE` matching for code identifiers, policy numbers, or hyphenated tokens (e.g., `POL-HR-2041`).
   - Ranks matches using PostgreSQL `ts_rank_cd`.

---

## 10. Reciprocal Rank Fusion (RRF)

To merge disjoint score distributions from vector similarity and BM25/FTS without arbitrary score normalization weights, the engine implements **Reciprocal Rank Fusion (RRF)**:

$$\text{RRF Score}(d) = \sum_{m \in M} \frac{1}{k + r_m(d)}$$

Where:
- $M$ is the set of retrieval branches (Dense, Lexical).
- $r_m(d)$ is the 1-based rank of document chunk $d$ in branch $m$.
- $k$ is the smoothing constant configured via `HYBRID_RRF_K` (default: `60`).

Chunks retrieved by both channels receive compounded reciprocal scores, surfacing documents that exhibit both semantic relevance and precise lexical matches.

---

## 11. Stage 4 Cross-Encoder Reranking

For ultra-high precision, hybrid candidates can be passed through a local cross-encoder model:

- **Activation**: Enabled when `RETRIEVAL_MODE=hybrid` and `RERANKING_ENABLED=true`.
- **Model**: `BAAI/bge-reranker-v2-m3` executed locally on CPU via `sentence-transformers`.
- **Candidate Pool**: RRF retrieves top `RERANK_CANDIDATE_K` (default: `20`) chunks.
- **Scoring**: Full question-passage cross-attention scoring in batches of `RERANK_BATCH_SIZE` (default: `16`).
- **Safety Cap**: Passages are truncated to `RERANK_MAX_CHARS` (default: `24000`) for scoring safety without mutating stored text.
- **Graceful Fallback**: If cross-encoder inference encounters memory or hardware issues, the engine falls back to standard RRF ranking when `RERANKING_FALLBACK=true`.

---

## 12. Metadata Filtering

Retrieval supports structured metadata pre-filtering applied directly at the SQL level before Top-K selection:

```json
{
  "question": "What are the travel reimbursement limits?",
  "filters": {
    "category": "finance",
    "source": "handbook-2026",
    "tags": ["expenses", "travel"],
    "uploaded_from": "2026-01-01T00:00:00Z",
    "uploaded_to": "2026-12-31T23:59:59Z",
    "page_from": 10,
    "page_to": 25,
    "document_ids": ["3fa85f64-5717-4562-b3fc-2c963f66afa6"]
  }
}
```

All specified filter predicates are combined via `AND` logic within the candidate queries.

---

## 13. Conversational Chat and History

- **Stateless API, Stateful Database**: Dialogue history is maintained in PostgreSQL tables `conversations` and `messages`.
- **Sliding Prompt Window**: `CONVERSATION_HISTORY_LIMIT` (default: `10`) recent messages are injected into the system prompt for co-reference resolution.
- **Untrusted Context Isolation**: Previous conversational turns and retrieved context are explicitly tagged as untrusted data blocks to safeguard against prompt injection.
- **Strict Grounding Refusal**: When document retrieval yields no matches above threshold, generation is skipped entirely, returning a deterministic refusal message with zero citations.

---

## 14. Authentication and Authorization

- **Password Hashing**: Argon2id via `argon2-cffi` with OWASP-recommended parameters (time cost 2, 64 MB memory cost, parallelism 2).
- **Access Tokens**: Short-lived JWTs (`ACCESS_TOKEN_EXPIRE_MINUTES=15`) signed with `HS256` and validated via PyJWT.
- **Refresh Tokens**: Cryptographically random 48-byte URL-safe tokens stored as SHA-256 hashes in PostgreSQL; delivered via `HttpOnly`, `SameSite=Lax` cookies.
- **Strict Secret Enforcement**: Configuration strictly requires `JWT_SECRET_KEY` (minimum 32 characters) and rejects placeholder values in production.
- **Bootstrap Admin**: Optional automatic provisioning of an initial admin user via `BOOTSTRAP_ADMIN_EMAIL` and `BOOTSTRAP_ADMIN_PASSWORD`.

---

## 15. Organizations and Workspaces

Multi-tenancy is structured into a two-level hierarchy:

1. **Organization**: Represents the enterprise or account boundary.
   - Roles: `OWNER`, `ADMIN`, `MEMBER`, `BILLING`.
2. **Workspace**: Project-level isolation container for documents, chunks, conversations, and alert rules.
   - Roles: `WORKSPACE_ADMIN`, `CONTRIBUTOR`, `VIEWER`.
   - **Isolation**: All document queries, vector lookups, and conversational interactions are scoped to the active workspace header (`X-Workspace-Id`).
3. **Document Access Control Lists (ACLs)**: Fine-grained read/write permission grants attached directly to individual documents.

---

## 16. Audit Logs, Tracing, and Alerting

### Immutable Audit Trails
- Records user identity, workspace ID, client IP, action type (`AUTH_LOGIN`, `DOCUMENT_UPLOAD`, `DOCUMENT_DELETE`, `CHAT_QUERY`, `ACL_UPDATE`), and structured metadata.
- Enforced at the schema level with immutable foreign-key relationships.

### Distributed Query Tracing
- Captures query lifecycle execution: overall latency, vector embedding duration, dense SQL duration, lexical SQL duration, RRF fusion latency, reranking duration, LLM Time-To-First-Token (TTFT), total generation time, and token usage.
- Automated cleanup via configurable retention policies (`TRACE_RETENTION_DAYS=30`).

### Platform Alerting & Anomaly Detection
- Evaluates real-time health against configurable threshold rules:
  - Error rate percentages (`TRACE_ALERT_ERROR_RATE_PERCENT`).
  - High P95 latency breaches (`TRACE_ALERT_P95_LATENCY_MS`).
  - Upstream AI provider failure rates (`TRACE_ALERT_PROVIDER_ERROR_PERCENT`).
  - Unusually high no-context retrieval rates (`TRACE_ALERT_NO_CONTEXT_PERCENT`).
- Automated incident generation with acknowledgment and resolution workflows.

---

## 17. Project Folder Structure

```
rag-knowledge-assistant/
├── .env.example                  # Environment variable template
├── .gitignore                    # Comprehensive repository ignore rules
├── docker-compose.yml            # Multi-container orchestration specification
├── LICENSE                       # MIT License
├── README.md                     # Project documentation
│
├── .github/
│   └── workflows/
│       └── ci.yml                # Automated CI pipeline (Pytest + Eval Gate)
│
├── backend/
│   ├── Dockerfile                # Production backend container definition
│   ├── requirements.txt          # Pinned Python package dependencies
│   ├── alembic.ini               # Database migration configuration
│   │
│   ├── alembic/
│   │   ├── env.py                # Alembic migration environment
│   │   └── versions/             # 13 incremental migration revisions
│   │
│   ├── app/
│   │   ├── main.py               # FastAPI application entry point & lifespan
│   │   │
│   │   ├── api/v1/               # Versioned REST API routers
│   │   │   ├── alert_rules.py    # Alert rule CRUD endpoints
│   │   │   ├── alerts.py         # Alert management & evaluation
│   │   │   ├── audit_logs.py     # Audit log search & verification
│   │   │   ├── auth.py           # Registration, login, token refresh, user profile
│   │   │   ├── chat.py           # Synchronous & SSE streaming chat endpoints
│   │   │   ├── conversations.py  # Conversation lifecycle management
│   │   │   ├── documents.py      # Upload, retrieval, deletion, and ACL routes
│   │   │   ├── health.py         # System liveness & readiness checks
│   │   │   ├── organizations.py  # Organization & membership management
│   │   │   ├── router.py         # Central v1 API router assembly
│   │   │   ├── traces.py         # Query trace telemetry & analytics
│   │   │   └── workspaces.py     # Workspace management & tenancy
│   │   │
│   │   ├── core/                 # Core cross-cutting infrastructure
│   │   │   ├── bootstrap.py      # Automated admin seeding
│   │   │   ├── config.py         # Pydantic Settings application config
│   │   │   ├── exceptions.py     # Global error handling & HTTP exceptions
│   │   │   ├── logging.py        # Structured application logging
│   │   │   ├── permissions.py    # RBAC permission evaluators
│   │   │   ├── security.py       # Argon2id hashing & JWT operations
│   │   │   └── workspace_context.py # Tenancy header resolution
│   │   │
│   │   ├── db/                   # Database engine & domain models
│   │   │   ├── base.py           # SQLAlchemy declarative Base
│   │   │   ├── database.py       # Engine pool & session lifecycle
│   │   │   └── models.py         # SQLAlchemy ORM domain entities
│   │   │
│   │   ├── repositories/         # Database persistence abstractions
│   │   ├── schemas/              # Pydantic request/response data contracts
│   │   │
│   │   └── services/             # Pure business logic services
│   │       ├── ai/               # AI Provider abstraction & Gemini implementation
│   │       ├── alerting/         # Anomaly detection & rule evaluation
│   │       ├── tracing/          # Observability tracer & analytics
│   │       ├── chunker.py        # Text chunking algorithms
│   │       ├── document_service.py # Document processing orchestrator
│   │       ├── embedding_service.py # Vector embedding management
│   │       ├── fusion.py         # Reciprocal Rank Fusion implementation
│   │       ├── pdf_parser.py     # PDF validation & extraction
│   │       ├── rag.py            # RAG coordination service
│   │       ├── rerank.py         # Cross-encoder reranker
│   │       ├── retrieval.py      # Dense & hybrid SQL search
│   │       └── sse.py            # Server-Sent Events stream formatting
│   │
│   ├── evaluation/               # Deterministic RAG evaluation harness
│   │   ├── run.py                # Evaluation CLI entrypoint
│   │   ├── datasets/             # Frozen evaluation question suites
│   │   └── reports/              # Output evaluation scorecards (gitignored)
│   │
│   ├── scripts/                  # Standalone administrative scripts
│   │   ├── smoke_gemini.py       # Live Gemini API smoke test
│   │   └── smoke_e2e.py          # End-to-end ingestion and chat verification
│   │
│   └── tests/                    # 37 comprehensive pytest test modules
│
├── frontend/
│   ├── Dockerfile                # Frontend development container
│   ├── package.json              # NPM dependencies & scripts
│   ├── tsconfig.json             # TypeScript compiler settings
│   ├── vite.config.ts            # Vite bundler configuration
│   ├── tailwind.config.js        # Tailwind CSS design system
│   │
│   └── src/
│       ├── main.tsx              # React application bootstrapping
│       ├── App.tsx               # Root view & routing controller
│       ├── components/           # Modular UI components
│       ├── pages/                # Top-level view controllers
│       ├── services/             # HTTP & SSE API communication
│       └── types/                # Frontend TypeScript interfaces
│
└── storage/
    └── documents/                # Local PDF storage directory (gitignored)
        └── .gitkeep              # Directory placeholder
```

---

## 18. Environment Setup

Create your local `.env` configuration from the provided template:

```bash
cp .env.example .env
```

### Essential Environment Variables

```ini
# Application Environment
APP_ENV=development
LOG_LEVEL=INFO

# Database Connection
POSTGRES_USER=rag_user
POSTGRES_PASSWORD=your_secure_db_password
POSTGRES_DB=rag_knowledge
POSTGRES_PORT=5432
DATABASE_URL=postgresql+psycopg://rag_user:your_secure_db_password@postgres:5432/rag_knowledge

# CORS Configuration
FRONTEND_ORIGIN=http://localhost:5173

# Frontend API URL
VITE_API_BASE_URL=http://localhost:8000

# Google Gemini API
GEMINI_API_KEY=your_gemini_api_key_here
LLM_MODEL=gemini-2.0-flash
EMBEDDING_MODEL=gemini-embedding-2
EMBEDDING_DIMENSION=768

# JWT Authentication (Must be >= 32 characters)
JWT_SECRET_KEY=your_random_32_character_secret_key_here
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=15
REFRESH_TOKEN_EXPIRE_DAYS=7

# Initial Bootstrap Admin (Optional)
BOOTSTRAP_ADMIN_EMAIL=admin@example.com
BOOTSTRAP_ADMIN_PASSWORD=your_strong_admin_password
BOOTSTRAP_ADMIN_NAME=Platform Administrator

# RAG Ingestion & Search Defaults
CHUNKING_STRATEGY=fixed_word_window
CHUNK_SIZE=700
CHUNK_OVERLAP=100
RAG_TOP_K=5
RAG_SIMILARITY_THRESHOLD=0.7
RETRIEVAL_MODE=dense
```

Generate a secure 32-byte hexadecimal JWT secret via Python:

```bash
python -c "import secrets; print(secrets.token_hex(32))"
```

---

## 19. Local Development Instructions

### Prerequisites
- Python 3.12+
- Node.js 20+ & npm
- PostgreSQL 16 with `pgvector` extension

### 1. Backend Setup
```bash
cd backend
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

pip install --upgrade pip
pip install -r requirements.txt

# Run migrations
alembic upgrade head

# Start FastAPI development server
uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

### 2. Frontend Setup
```bash
cd frontend
npm install
npm run dev
```

Visit the dashboard at `http://localhost:5173`.

---

## 20. Docker Setup

The easiest way to run the entire stack is with Docker Compose:

```bash
docker compose up --build -d
```

### Container Layout
- **PostgreSQL (`rag-postgres`)**: Port `5432` with pre-installed `pgvector/pgvector:pg16`.
- **FastAPI Backend (`rag-backend`)**: Port `8000` with hot-reload and automatic migration execution.
- **React Frontend (`rag-frontend`)**: Port `5173` running the Vite development server.

### Tear Down
```bash
docker compose down
# To remove all persistent volumes (including database data):
docker compose down -v
```

---

## 21. Database Migrations and pgvector Setup

All database schema evolutions are managed strictly through Alembic:

```bash
# Apply all pending migrations
docker compose exec backend alembic upgrade head

# Inspect migration history
docker compose exec backend alembic history

# Check current revision status
docker compose exec backend alembic current
```

### Migration History
1. `0001_enable_pgvector`: Enables PostgreSQL `vector` extension.
2. `0002_documents_and_chunks`: Creates `documents` and `document_chunks` with `vector(768)`.
3. `0003_conversations`: Creates `conversations` and `messages` tables.
4. `0004_document_metadata`: Adds `category`, `source`, and `tags` columns.
5. `0005_chunk_content_tsv`: Adds generated `tsvector` column and GIN index for lexical search.
6. `0006_orgs_and_workspaces`: Implements multi-tenant Organizations and Workspaces.
7. `0007_auth_and_memberships`: Introduces Users, Passwords, Refresh Tokens, and Org Memberships.
8. `0008_auth_rbac_management`: Extends RBAC roles across workspaces.
9. `0009_document_acls`: Granular document access control lists.
10. `0010_audit_logs`: Append-only audit logging architecture.
11. `0011_audit_log_fk_immutability`: Immutability constraints for audit trails.
12. `0012_query_traces`: Query execution telemetry and latency tracing.
13. `0013_platform_alerts_and_rules`: Alert rules and anomaly detection records.

---

## 22. API Endpoint Documentation

When running, explore interactive OpenAPI documentation at `http://localhost:8000/docs`.

### Authentication
- `POST /api/v1/auth/register`: Register a new user account.
- `POST /api/v1/auth/login`: Authenticate credentials, set refresh cookie, return access token.
- `POST /api/v1/auth/refresh`: Issue a new access token using the HTTP-only refresh cookie.
- `POST /api/v1/auth/logout`: Invalidate the current session and revoke refresh tokens.
- `GET /api/v1/auth/me`: Retrieve current user profile and memberships.

### Tenancy & Workspaces
- `GET /api/v1/workspaces`: List workspaces accessible to current user.
- `POST /api/v1/workspaces`: Create a new workspace.
- `GET /api/v1/workspaces/{id}/members`: List members in a workspace.
- `POST /api/v1/workspaces/{id}/members`: Add or update workspace role for a user.

### Document Management
- `POST /api/v1/documents`: Upload and process a PDF (`multipart/form-data`).
- `GET /api/v1/documents`: List uploaded documents with status and metadata.
- `GET /api/v1/documents/{id}`: Retrieve detailed document status and metadata.
- `PATCH /api/v1/documents/{id}`: Update document category, source, or tags.
- `DELETE /api/v1/documents/{id}`: Delete document, cascading chunks and disk files.
- `GET /api/v1/documents/{id}/acl`: Retrieve document access control entries.
- `POST /api/v1/documents/{id}/acl`: Grant explicit permissions to a user.

### Chat & Retrieval
- `POST /api/v1/chat`: Synchronous RAG question-answering with JSON response.
- `POST /api/v1/chat/stream`: Real-time streaming RAG question-answering via Server-Sent Events.
- `GET /api/v1/conversations`: List user conversations in workspace.
- `GET /api/v1/conversations/{id}`: Retrieve full conversation message history.
- `DELETE /api/v1/conversations/{id}`: Delete conversation and associated messages.

### Observability & Alerts
- `GET /api/v1/traces`: Query execution trace history with duration breakdowns.
- `GET /api/v1/traces/analytics`: Aggregated latency, TTFT, and token usage analytics.
- `GET /api/v1/audit-logs`: Query immutable security audit log trail.
- `GET /api/v1/alerts`: List active and historical platform alerts.
- `POST /api/v1/alerts/{id}/acknowledge`: Mark an alert as acknowledged.
- `POST /api/v1/alerts/{id}/resolve`: Mark an alert as resolved.

---

## 23. Testing Instructions

### Backend Automated Test Suite
The backend contains 37 pytest test modules verifying unit logic, integration boundaries, and end-to-end flows:

```bash
# Run all tests inside Docker container
docker compose exec backend pytest

# Run tests locally with coverage summary
cd backend
pytest --maxfail=1 -v
```

### Frontend Build & Typecheck
```bash
# Execute TypeScript compilation and Vite production build
cd frontend
npm run build
```

### Deterministic Offline RAG Evaluation
The repository includes an evaluation harness that scores retrieval against frozen benchmark datasets without incurring API costs:

```bash
# Run deterministic offline evaluation against baseline
docker compose exec backend python -m evaluation.run --embedder local --check-baseline --no-save

# Run lexical companion dataset evaluation
docker compose exec backend python -m evaluation.run --embedder local \
  --dataset evaluation/datasets/rag_eval_lexical.json --check-baseline --no-save
```

### Live Smoke Tests
```bash
# Test Gemini API connectivity
docker compose exec backend python -m scripts.smoke_gemini

# Run end-to-end ingestion and retrieval smoke test
docker compose exec backend python -m scripts.smoke_e2e
```

---

## 24. Known Limitations

- **Scanned / Image-Only PDFs**: The system relies on `pypdf` for text extraction. OCR (Optical Character Recognition) for rasterized scans is not currently implemented.
- **Single Vector Model per Table**: The schema binds chunk embeddings to a specific dimension (`768`). Changing embedding dimensions requires altering the vector column or re-indexing.
- **Synchronous Ingestion**: PDF parsing, chunking, and embedding occur synchronously during the `POST /api/v1/documents` HTTP request. Very large documents (>50 MB) should be processed via background task workers (e.g., Celery/ARQ).
- **Exact Vector Search**: Uses exact cosine distance calculation via pgvector. For corpora exceeding 500,000 chunks, an HNSW or IVFFlat index should be created.

---

## 25. Future Improvements

- **Asynchronous Task Queue**: Transition PDF ingestion to background workers (Redis + ARQ or Celery) with WebSocket status updates.
- **Optical Character Recognition (OCR)**: Integrate Tesseract or Google Cloud Vision for scanned documents and image extraction.
- **Agentic Query Transformation**: Implement query expansion and multi-step conversational query rewriting prior to retrieval.
- **HNSW Indexing**: Implement automated vector index tuning based on corpus chunk scale.
- **Multi-Modal Support**: Expand parsing and embedding to image figures, charts, and table structures.

---

## License

This project is open-source software licensed under the [MIT License](LICENSE).
