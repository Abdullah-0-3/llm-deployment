# Simple LLM Deployment (LLMOps Learning Project)

A production-style LLMOps project built step-by-step with FastAPI, Celery, Redis, PostgreSQL/pgvector, Ollama, Nginx, Prometheus, and Grafana.

This README documents what is implemented so far, how the system works, and how to run it (including manual model installation, since model-puller is disabled).

## Architecture
<p align="center">
  <img src="LLMOps Diagram.png" alt="Alt Text">
</p>


## Architecture Workflow

```mermaid
flowchart LR
  subgraph Client_Layer["Client Layer"]
    External_App["External User Application"]
  end

  subgraph Compose_Infra["Infrastructure (Docker Compose)"]
    direction TB

    subgraph Proxy_Layer["API and Reverse Proxy"]
      direction LR
      Nginx["Reverse Proxy (Nginx)"]
      FastAPI["LLM API Service (FastAPI)"]
    end

    subgraph Queue_Layer["Async Queue"]
      direction LR
      RedisBroker["Redis Broker"]
      CeleryWorker["Celery Worker"]
    end

    subgraph Model_Layer["Inference"]
      Ollama["Ollama"]
    end

    subgraph Data_Layer["Data and State"]
      direction LR
      RedisCache["Redis Cache"]
      PostgreSQL["PostgreSQL + pgvector"]
      LLMLogs["llm_logs"]
      SessionStore["session_messages"]
      RAGStore["rag_chunks"]
    end

    subgraph Obs_Layer["Observability"]
      direction LR
      Prometheus["Prometheus"]
      Grafana["Grafana"]
    end
  end

  subgraph CICD["CI/CD Pipeline"]
    GitHubActions["GitHub Actions"]
    ContainerRegistry["Container Registry"]
  end

  GitHubActions -->|"Build and Push Images"| ContainerRegistry
  ContainerRegistry -->|"Deploy Compose Artifacts"| Compose_Infra

  External_App -->|"HTTP Request + API Key"| Nginx
  Nginx -->|"Proxy"| FastAPI

  FastAPI -->|"Sync Inference"| Ollama
  FastAPI -->|"Cache Read/Write"| RedisCache
  FastAPI -->|"Enqueue Async Job"| RedisBroker
  RedisBroker -->|"Consume Job"| CeleryWorker
  CeleryWorker -->|"Async Inference"| Ollama

  FastAPI -->|"Store Generation Metadata"| LLMLogs
  FastAPI -->|"Store/Read Session Memory"| SessionStore
  FastAPI -->|"RAG Vector Search/Insert"| RAGStore

  LLMLogs --> PostgreSQL
  SessionStore --> PostgreSQL
  RAGStore --> PostgreSQL

  CeleryWorker -->|"Store Async Results/Logs"| LLMLogs

  Prometheus -->|"Scrape /metrics"| FastAPI
  Prometheus -->|"Scrape /metrics"| CeleryWorker
  Grafana -->|"Query Metrics"| Prometheus
```

## What Has Been Implemented?

### 1) API Hardening
- API key authentication (`X-API-Key` header)
- Request validation with Pydantic models
- In-memory rate limiting per API key

### 2) Async Processing
- Redis-backed Celery queue
- Async endpoints:
  - `POST /submit`
  - `GET /result/{task_id}`

### 3) Caching Layer
- Redis prompt-response cache for synchronous requests
- TTL-based entries and SHA-256 prompt keying

### 4) Persistent Storage
- PostgreSQL logging of generations
- Stored fields include:
  - prompt
  - full model response
  - latency
  - timestamp

### 5) Advanced Observability
- API metrics exposed at `/metrics`
- Worker metrics exposed at port `8001` (`/metrics`)
- Prometheus scrapes API + worker
- Grafana datasource + dashboards provisioned from local files

### 6) Conversation Memory
- Session memory stored in PostgreSQL (`session_messages`)
- Optional `session_id` in `/generate` and `/submit`
- Previous conversation turns are injected into prompt construction

### 7) RAG (Retrieval-Augmented Generation)
- Embeddings via Ollama embedding model (`OLLAMA_EMBED_MODEL`)
- pgvector storage (`rag_chunks` table)
- Ingestion endpoint: `POST /ingest`
- Retrieval before generation for non-session requests

## Simple Architecture

```mermaid
flowchart LR
    U[User / Client] --> N[Nginx :80]

    N --> A[FastAPI API]
    A --> O[Ollama]
    A --> R[(Redis)]
    A --> P[(PostgreSQL + pgvector)]
    A --> C[Celery Broker/Backend on Redis]

    C --> W[Celery Worker]
    W --> O
    W --> P
    W --> R

    A --> M1[/metrics/]
    W --> M2[Worker Metrics :8001/metrics]

    PR[Prometheus] --> M1
    PR --> M2
    G[Grafana] --> PR
```

## Request Flow (Sync + RAG + Session)

```mermaid
sequenceDiagram
    participant User
    participant API as FastAPI
    participant Redis
    participant PG as PostgreSQL/pgvector
    participant Ollama

    User->>API: POST /generate (prompt, optional session_id)

    alt session_id provided
        API->>PG: Load recent session messages
        API->>API: Build prompt with conversation history
        API->>Ollama: Generate answer
        API->>PG: Save user + assistant messages
    else no session_id
        API->>PG: Vector search (RAG) using embedded query
        API->>API: Build prompt with retrieved context (if any)
        API->>Redis: Cache lookup (only when no RAG context)
        alt cache hit
            Redis-->>API: Cached response
        else cache miss
            API->>Ollama: Generate answer
            API->>Redis: Save cache
        end
    end

    API->>PG: Save generation log
    API-->>User: JSON response
```

## Project Structure

- `docker-compose.yml` - full stack orchestration
- `api/` - FastAPI app + worker code
- `api/src/app_factory.py` - routes and dependency wiring
- `api/src/services.py` - generation, session memory, and RAG service logic
- `api/src/storage.py` - PostgreSQL + pgvector persistence
- `api/src/tasks.py` - Celery task execution path
- `prometheus.yml` - Prometheus scrape config
- `grafana/` - provisioning for datasource and dashboards
- `run.sh` - quick local prompt runner (prints only response text)

## Prerequisites

- Docker + Docker Compose
- Bash shell (for `run.sh`)

## Environment Setup

1. Copy env file:

```bash
cp .env.example .env
```

2. Update required values in `.env`:
- `API_KEY`
- `OLLAMA_MODEL`
- `OLLAMA_EMBED_MODEL`

Defaults already exist for local development.

## Start the Stack

```bash
docker compose up --build -d
```

Check status:

```bash
docker compose ps
```

## Install Models Manually (Important)

Model-puller is disabled currently, so install models manually after containers are up:

```bash
docker exec ollama ollama pull tinyllama
docker exec ollama ollama pull nomic-embed-text
```

Use your `.env` values if you changed model names.

Verify installed models:

```bash
docker exec ollama ollama list
```

## Run and Test

### Health

```bash
curl -s http://localhost/
```

### Sync generation

```bash
curl -s -X POST http://localhost/generate \
  -H "Content-Type: application/json" \
  -H "X-API-Key: adminLLM" \
  --data-raw '{"prompt":"Is apple healthy?"}'
```

### Quick runner script

```bash
./run.sh "Is apple healthy?"
```

### Async generation

```bash
curl -s -X POST http://localhost/submit \
  -H "Content-Type: application/json" \
  -H "X-API-Key: adminLLM" \
  --data-raw '{"prompt":"Explain caching in one paragraph"}'
```

Use returned `task_id`:

```bash
curl -s -H "X-API-Key: adminLLM" http://localhost/result/<task_id>
```

### Session memory test

```bash
curl -s -X POST http://localhost/generate \
  -H "Content-Type: application/json" \
  -H "X-API-Key: adminLLM" \
  --data-raw '{"prompt":"My name is Alex","session_id":"demo-1"}'

curl -s -X POST http://localhost/generate \
  -H "Content-Type: application/json" \
  -H "X-API-Key: adminLLM" \
  --data-raw '{"prompt":"What is my name?","session_id":"demo-1"}'
```

### RAG ingest + query

Ingest knowledge:

```bash
curl -s -X POST http://localhost/ingest \
  -H "Content-Type: application/json" \
  -H "X-API-Key: adminLLM" \
  --data-raw '{"text":"Apples are rich in fiber and vitamin C.","source":"notes"}'
```

Ask related question:

```bash
./run.sh "Are apples healthy?"
```

## Observability

- API metrics: `http://localhost/metrics`
- Prometheus: `http://localhost:9090`
- Grafana: `http://localhost:3000`

Note: If Grafana login seems stale, reset persistent data once:

```bash
docker compose down -v
docker compose up --build -d
```

## Database Checks

### List tables

```bash
docker compose exec postgres psql -U llmops -d llmops -c "\dt"
```

### Generation logs

```bash
docker compose exec postgres psql -U llmops -d llmops -c "SELECT COUNT(*) AS total_logs FROM llm_logs;"
```

### Session messages

```bash
docker compose exec postgres psql -U llmops -d llmops -c "SELECT COUNT(*) AS total_session_messages FROM session_messages;"
```

### RAG chunks

```bash
docker compose exec postgres psql -U llmops -d llmops -c "SELECT id, source, left(content, 120) AS content_preview FROM rag_chunks ORDER BY id DESC LIMIT 20;"
```

## Notes and Current Limitations

- Model auto-pulling is intentionally disabled for now.
- RAG chunking is simple sentence/length based (good for learning, not yet advanced document parsing).
- Rate limiter is in-memory (single-node dev setup behavior).

## Next Roadmap Items (Not Yet Implemented)

From your plan, these are still pending:
- 8) React (UI)
- 9) CI/CD Pipelines (GitHub Actions)
- 10) Model Abstraction Layer
- 11) Kubernetes Deployment
- 12) Costing & Tracking
- 13) Deployment