# Unified Qdrant deployment and Agent contracts

The following identity describes the historical public-only baseline. It is
input to a rebuild, not the name or schema that a new deployment must preserve.
Runtime artifacts remain outside Git and must be provisioned before
`RAG_ENABLED=true`.

- Collection: `collection_e55166f798ef1c361c72de9a` (11 documents, 941 chunks)
- Deployment: `deployment_357bd9c84d8404fae42c2740`
- Qdrant collection: `rag_qwen3_embedding_4b_v2`
- Embedding: Qwen3-Embedding-4B, 2560 dimensions
- Retrieval: dense-only, top 20 candidates, top 5 final results, 8192 context tokens
- Reranker: disabled; `rerank_limit=20` remains part of the stable config schema

The 8192-token limit belongs to the retrieval service and remains available to
non-Agent consumers. The B2 Agent adapter applies a second, deterministic
extractive budget: at most 2048 estimated tokens across returned context and
at most 512 per result. It prefers sentence or paragraph boundaries and marks
cut text with `…`; Evidence objects and source locators remain unchanged.

The authoritative environment mapping is `backend/core/utils/config.py`; the
deployable template is `.env.example`. A deployment manifest owns the indexed
embedding identity, while `RAG_EMBEDDING_MODEL_PATH` may point at an equivalent
local model copy used to load it.

## Agent result contracts

`get_knowledge_base_stats` remains the public deployment metadata contract.
Public-only retrieval retains the separated v2 model/display/audit adapter in
`agent_api.py`; the Agent-facing federation wraps it together with personal
results as `retrieve_knowledge.unified.v1`. The final serialized model JSON is
still limited to 2048 tokens, while complete source material stays in the audit
projection. Contract changes require a new version, updated fixtures, and
regenerated training schema/data; they must not be introduced silently.

## Unified collection protocol

Public and personal Points use the one collection named by
`RAG_QDRANT_COLLECTION`. `PERSONAL_KB_QDRANT_COLLECTION` is only a deprecated
configuration alias to that same value; it is not a second deployment knob.
Every Point is selected by server-built Qdrant filters:

- public: `scope=public + visible=true + index_generation_id`;
- personal: `scope=personal + visible=true + user_id + knowledge_base_id + kb_generation_id`, plus the SQLite live-file allowlist;
- personal file deletion: the personal filter above plus `file_id`, followed by an exact count-to-zero check.

The unified collection requires keyword payload indexes for `scope`,
`content_role`, `index_generation_id`, `kb_generation_id`, `user_id`,
`knowledge_base_id`, `file_id`, and `document_id`, plus a bool index for
`visible`. `user_id` is always injected from authenticated server context. It
is never accepted from the model or trusted merely because a client supplied
it.

The frontend continues to send `knowledge_sources` and an optional
`personal_knowledge_base_id`. The Agent sees only `retrieve_knowledge`.
Server-bound selection decides whether that call searches public, personal, or
both scopes. A two-scope search is merged by source-level RRF, because public
and personal raw scores do not share a comparable scale.

## Rebuild and cutover

Build a new named collection on every target machine. Do not reinterpret,
rename, or mutate an existing experimental/public/personal collection in
place:

1. Choose a fresh `RAG_QDRANT_COLLECTION` name and build the public deployment into it.
2. Verify the public generation, exact public Point count, payload indexes, and a `scope=public` query.
3. Start the personal lifecycle against the same name. It restores a compatible unified snapshot or rebuilds only `scope=personal` from SQLite and durable sources.
4. Verify public and personal scope counts, one public-only query, one personal-only query, and one combined query for an authenticated test user.
5. Delete a test personal document and prove only its `user_id + knowledge_base_id + kb_generation_id + file_id` Points reach zero while public count remains unchanged.
6. Switch the deployment manifest/environment to the verified collection. Retain the old collection until rollback and backup requirements are satisfied.

Use this procedure independently for local development and the 8×A800 system;
no collection currently present on either machine is an input assumption of
the backend protocol.

## Personal lifecycle in the unified collection

Run one ESA Uvicorn worker and one Qdrant process per Slurm Job. Keep SQLite,
uploaded sources, DocIR/Chunk artifacts, and `PERSONAL_KB_SNAPSHOT_ROOT` on
persistent storage; keep active Qdrant storage and parsing work under the
Job-local temporary root.

Startup restores a checksummed snapshot whose embedding, index, locator,
collection, and point count are compatible. If its sequence is below SQLite's
global mutation high-water, startup keeps readiness false, verifies that every
intervening applied outbox sequence is retained and continuous, and performs an
idempotent authoritative-state reconcile without rewinding the high-water.
Mutation journal rows are intentionally retained indefinitely; no ordinary job
or snapshot-retention cleanup deletes them, so every retained snapshot remains
a valid replay cursor. Before lifespan startup completes, interrupted
`running/applying` jobs are requeued and drained in per-user revision order. A
terminal replay failure leaves personal retrieval not-ready for an operator to
inspect and explicitly retry. If no compatible snapshot is usable, startup
clears and rebuilds only `scope=personal` from the committed SQLite generation
state and durable sources; it never recreates the shared collection. Unified
snapshots bind the public generation/count, which are checked again after
restore before personal readiness. The
personal worker starts only after that validation. Shutdown first stops new
personal jobs, waits for active checkpoints, and then flushes a final snapshot
while Qdrant is still running. A stale snapshot is never served as current.

## Personal file preview

Original content and downloads are tenant-authorized, single-range streams from
an already-open descriptor. The UI uses the separate bounded preview endpoint:
ingestion persists at most 512 KiB of extracted UTF-8 text, while images use a
maximum 1600-pixel thumbnail. These derived files live below the owning file's
artifact directory and are removed by the existing file cleanup and user purge.

Office files safely fall back to extracted text. To enable Office-to-PDF views,
set `PERSONAL_KB_LIBREOFFICE_BIN` to an absolute executable path and tune
`PERSONAL_KB_OFFICE_PREVIEW_TIMEOUT_SECONDS` and
`PERSONAL_KB_OFFICE_PREVIEW_MAX_BYTES`. Conversion uses no shell, creates an
isolated LibreOffice profile, verifies the only output is a bounded PDF, and
records a warning rather than publishing an invalid conversion. Changing the
converter identity changes the ingestion fingerprint and therefore requires a
rebuild. Do not mark the real Office fixture acceptance item complete until the
configured host binary and actual `doc/ppt/xls` corpus pass the full pipeline.

## Backup, retention, and capacity

Treat the main `user.db`, `PERSONAL_KB_ROOT/files`, and the checksummed personal
Qdrant snapshots/manifests as one backup set. For a consistent manual backup,
stop new HTTP writes, let the personal worker checkpoint and the final snapshot
finish, copy `user.db` with SQLite's backup API, then copy the personal root and
verify every snapshot manifest SHA-256. Restore the database and source tree
first; startup then validates/replays the newest compatible Qdrant snapshot or
rebuilds the derived collection. Never restore only one of these three layers
as if it were authoritative by itself.

Upload admission enforces per-file, per-batch, per-user, request-body, expanded
archive, image-pixel, page-count, and persistent/temp free-space limits. SQLite
quota reservations prevent concurrent requests from overselling user capacity.
Alert on the internal metrics endpoint when queue or failed counts are nonzero,
cleanup counts grow, readiness is false, or the mutation/snapshot sequence gap
persists. Cluster monitoring must additionally alert on Qdrant local-storage
and persistent-root free space before they reach the configured safety margin;
reject uploads rather than evicting un-snapshotted personal data.

Operational commands use the same main SQLite database and never accept a
document path from the caller:

```bash
python -m backend.agent.rag.personal.cli \
  --database /persistent/path/user.db audit-user --user-id USER_ID
python -m backend.agent.rag.personal.cli \
  --database /persistent/path/user.db retry-job --user-id USER_ID --job-id JOB_ID
python -m backend.agent.rag.personal.cli \
  --database /persistent/path/user.db retry-generation-cleanup \
  --user-id USER_ID --generation-id GENERATION_ID
python -m backend.agent.rag.personal.cli \
  --database /persistent/path/user.db cleanup-orphans
python -m backend.agent.rag.personal.cli \
  --database /persistent/path/user.db cleanup-audit --retention-days 90
```

`audit-user` compares SQLite's committed visible count with a tenant-filtered
Qdrant count. `retry-job` only requeues an owned terminal failure and its
unsequenced outbox mutation; normal revision ordering still applies.
`cleanup-orphans` applies the configured retention period and skips every UUID
directory still referenced by SQLite. `cleanup-audit` removes only old
successful/cancelled jobs, completed tombstones, empty retired generations, and
already invalid/deleted snapshot records. It never deletes failed retry state or
mutation-journal rows, so audit retention cannot break recovery.

Account deletion must call `PersonalKnowledgeBaseService.purge_user(user_id)`
and require the returned purge status to be `completed` before deleting the main
`users` row. The purge freezes new tenant writes and retrieval, captures every
owned file ID, deletes all tenant points with a `scope=personal + user_id`
filter, proves absence with both exact count and scroll, removes sources and
derived artifacts, and records a global mutation sequence. A new snapshot is
then restored into a disposable collection to prove the entire user is absent;
all older snapshots are destroyed before completion. The purge audit table has
no user foreign key by design, so the replay/deletion proof survives the final
main-database cascade. If any step fails, do not delete the `users` row; retry
the same durable purge instead.

The reverse proxy must reject oversized bodies before forwarding them. Set its
request-body limit to the same value as `PERSONAL_KB_MAX_REQUEST_BYTES` (the
default is 1 GiB plus 16 MiB multipart overhead), while the application ASGI
middleware independently enforces that ceiling. Multipart spill files are
forced under `PERSONAL_KB_TEMP_ROOT/multipart` on Job-local storage; startup
also verifies the configured free-space reserve on both temporary and
persistent roots.

Set `ESA_SHARED_COMPUTE_NODE=true` when the Slurm node is not exclusive. The
launcher then selects a Job-specific loopback HTTP port unless one is supplied,
starts Qdrant with a newly generated API key, exports the matching URL/key to
ESA, and refuses to attach a personal collection to an already-running local
process whose ownership it cannot prove. Keep `ESA_SHARED_COMPUTE_NODE=false`
only for an exclusive node or local development.

Run the read-only host verifier from the login/compute-node shell after the Job
environment has been exported (not from a container used by Codex):

```bash
backend/scripts/check_personal_kb_host.sh | tee personal-kb-host-check.txt
```

It does not create paths or repair permissions. A failure is evidence to inspect,
not authorization to run `chmod`, reinstall drivers, reload services, or reboot.

The remaining destructive recovery drills, genuine legacy Office full-chain
check, and live personal/federated evaluation are specified in
`PERSONAL_KB_ACCEPTANCE_RUNBOOK.md`. Run them only in a dedicated acceptance Job;
unit simulations are not a substitute for the resulting host evidence bundle.
