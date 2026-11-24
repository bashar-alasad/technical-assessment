# Multi-Agent RAG Platform at Scale

## Requirements

1. 2k QPS
2. P95 latency < 3s
3. 50M docs
4. Continuous document updates
5. Strict tenant isolation
6. SLA on answer quality

---

## Retrieval layer

### Embedding
**Embedding model:** `nomic-embed-text-v1.5`  
Self-hosted and strong balance between quality, cost, and latency. Offers better semantic embeddings than a 384-dim but at a lower cost and latency than a 1536-dim. MRL truncation, allowing a smaller and faster search. Good enough with a reranker sitting behind it.

### Chunking
512 tokens with 15% overlap

### Vector store
**Vector store choice:** OpenSearch  
Does BM25 keyword lexical search and kNN for vector backed by HNSW index searches in a hybrid system. Avoids having to maintain two systems rather than one.

### Index type
HNSW with int8 Quantization. Since documents are being continuously updated, HNSW can handle it without needing cluster training or the issue of recall drift. Turn on int8 quantization in index mapping to auto compress the vectors when indexing to cut down RAM usage. Instead of 4 bytes per dimension, brings it down to 1.

### Sharding
Separate by tenant, large tenants with large quantities of data get their own index. Small tenants share an index. Partitioned by `tenant_id` filter.

### Hybrid search
Run BM25 for top 50 for keywords and vector for top 50 for semantic meaning. Then combine them with Reciprocal Rank Fusion.

### Reranker
**Cross encoder:** `Qwen/Qwen3-Reranker-0.6B`  
Self-hosted for cost and latency. Reranks top 50 down to 5 to send to LLM.

---

## Agent orchestration

### Agent coordination
**Stateless orchestrator service:** FastAPI  
Use a DAG inside a stateless service to act as orchestrator.

Orchestrator sends query to router agent -> Router agent classifies intent and outputs in a structured JSON plan on whether docs and/or tools are needed and returns it -> Orchestrator reads plan and dispatches either retrieval agent, tool agent, or both. -> Worker agents hand back results to orchestrator's in-memory state object -> After all workers are complete, orchestrator sends combined JSON state to synthesis agent to stream answer.

### Pass state
- Each request carries a JSON.
- Immutable `tenant_id` injected by API gateway and passed through with read only permissions through DAG to avoid tenant scope leak via OpenSearch or internal API calls.
- Stripped down payloads, worker agents only return top 5 reranked chunks with metadata and filtered JSON from APIs to keep synthesis LLM cost and latency low.

### Failure timeout
- Tool agent limit <= 3 to avoid open ended loops.
- Tool time out ≤ 800 ms
- Read only calls get one retry.
- Circuit breaker stops calling a tool if its error rate spikes.
- Partial results if a tool fails, the synthesis will still answer from retrieval agent and state explicit status.

### Bound cost and latency
Run dependent stages sequentially but retrieval agent and tool agent in parallel via `asyncio.gather` to reduce middle stage latency.

### Early exit paths
- **Skip synthesis:** for deterministic lookups, bypass synthesis LLM and return clean API payload.
- **Skip RAG:** if router agent flags a live-data query, skip OpenSearch and reranking.

---

## Freshness

### Keeping index current under continuous updates without full indexing
**Distributed event streaming platform:** Kafka  
**Event driven ingestion:** Stream document creates, modifies, or deletes from source systems via Kafka into stateless ingestion workers.

### No full index
**Deterministic `chunk_id` and content hashing**  
Hash each document and its chunks before embedding them. When a document is modified, re-embed and insert only the modified chunks using the deterministic IDs from OpenSearch's bulk API. HNSW supports incremental inserts, so no need for index rebuild.

### Handling deletes
Single documents delete all correlating chunks with `doc_id` within the scope of `tenant_id`. OpenSearch marks them as deleted and purges the documents.

### Tenant data removal
- For large tenants with dedicated index -> Run an index drop, and purge its caches, raw documents in the storage and logs.
- For smaller tenants with shared index -> Revoke `tenant_id` at API gateway to make data inaccessible, then run an async delete by query in the background to avoid spiking cluster load for active tenants.

---

## Evaluation & Observability

### Offline eval
Create a "golden dataset" with version control with labeled relevant docs and reference answers that is continuously updated with failed production traces.

**Framework:** Ragas  
Run automated evals in CI to see where regressions happened. Score answers based on faithfulness and relevance by an LLM judge.
- **Retrieval:** Did vector store and reranker model put the correct chunks in the top 5 retrieved?
- **Generation:** Are all claims supported by retrieved chunks and tool outputs? Was the AI's output relevant to the user's query?

Block any prompt, reranker, or LLM change from deploying if faithfulness, relevance, and/or recall do not meet baseline threshold.

### Online monitoring

#### Sample traffic
Run async (avoids latency) LLM judge on 5% of live traffic to check how grounded answers are.
- Is every claim backed by a retrieved chunk or tool output?

#### Drift detection
Monitor the rolling averages of top-k retrieval and reranker scores to catch silent drops. If they trend down, the index is missing content users need or chunks are out of date. Also track query embedding drift against baseline. Shift means users are asking new questions index may not cover.

#### Per-tenant quality
Each signal is tracked per `tenant_id` thus one tenant's problem isn't hidden in overall average.  
Track p95 latency, sample groundedness, document citation rate, and user feedback.  
Alert when tenant drops below answer quality SLA (e.g. groundedness ≥ 95%)

### A/B testing
Ensure that the prompt, LLM, reranker, and retrieval settings are version controlled and place them together in a single config bundle.
1. **Shadow mode:** New bundle runs on live traffic to check latency and judge scores without impacting user experience.
2. **Canary:** Route 5% of traffic to the new bundle based on `session_id`, `tenant_id`, `user_id`, etc.
3. Compare scores of new bundle against current bundle, continuously ramp up if quality, latency, and cost are not negatively impacted.

### Model rollback
Bundle versions are placed behind feature flags so an automated alert can instantly flip traffic. Add the failures to the golden dataset for offline eval so the regressions can be caught in CI.

---

## Reliability & Cost

### Caching
**Exact + Semantic = Redis**  
Check an exact match cache first, then a semantic cache ONLY if similarity threshold is met (e.g. ≥ 0.95) scoped per `tenant_id`. Only cache static knowledge-base queries.

Each semantic cache entry stores `doc_id`(s) it used and is invalidated when Kafka sends update or delete for those documents

### Fallbacks when LLM provider degrades
Route LLMs through an AI gateway, if the primary provider spikes or service is down, route to a secondary provider. If both providers are failing, return just the top 5 reranked chunks with citations.

### Rate limiting
Per `tenant_id` token quota and QPS. Enforce via Redis (e.g. sliding window counters) so one noisy tenant does not exhaust 2k QPS or raise latency for all others.

### Dominant cost drivers and how to cut them
1. **Synthesis LLM:**
   - a. Early exit paths to skip synthesis on deterministic lookups
   - b. Send only the top 5 reranked chunks
   - c. Semantic caching + provider prefix caching for the static system prompt
   - d. Cap on output tokens
2. **GPU inference:**
   - a. Self-host with batch requests and rerank only 50 candidates.
   - b. Skip RAG when the router flags a live data query.
3. **OpenSearch RAM:**
   - a. Utilize int8 quantization.
   - b. Truncate vectors via MRL.
4. **Router agent**
   - a. Use a small and cheap model for classification.

---

## Two Biggest Risks

1. **Cross tenant data leakage**  
   A filter bug in a shared index, loose semantic cache match, or stale cache after document deletion could potentially return one tenant's data to another.  
   **De-risk:**
   - Enforce isolation in infrastructure: `tenant_id` always comes from auth token.
   - Cache keys and API credentials are tenant scoped.
   - Automated tests in CI: Cross-tenant tests that try to retrieve Tenant B's data using Tenant A's credentials.

2. **LLM provider latency or capacity at 2k QPS**  
   Synthesis LLM takes 50% of the latency budget (3s) and depends on external provider. Tail latency spikes or rate limits break p95.  
   **De-risk:**
   - Reserved throughput from two providers
   - Streaming responses
   - Hard timeouts with fallback to smaller model or retrieval mode only
   - Load testing at 2x peak QPS to validate failover and tail latency.