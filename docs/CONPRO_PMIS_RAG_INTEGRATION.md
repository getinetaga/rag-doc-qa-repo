# ConPro PMIS and Hybrid RAG Integration Design

Date: 2026-10-14

Status: **Documentation for review. The integration is not implemented.**

This document applies `RAG_HYBRID_ARCHITECTURE_PROPOSAL.md` to the existing
ConPro PMIS. It describes a proposed, incremental, read-only integration.
It does not authorize or perform implementation.

**Neither existing application was changed.** No code, UI, settings, database
schema, permissions, provider configuration, or running service was modified.
The Markdown document and its review PDF are the deliverables.

Update 2026-10-15: the user separately approved standalone RAG answer retention.
That feature is now implemented in the RAG working tree; it does not implement
the ConPro connector. See Section 11.3 and the RAG operational guide for its
30-day, opt-in, owner-only policy and local-FAISS limitations.

## 1. Evidence, scope, and limitations

### 1.1 Verified source boundaries

Two local working trees were inspected read-only:

| Application | Snapshot used | Verified foundation |
|---|---|---|
| Existing RAG application | Branch `rag`, commit `8344586`, plus its pre-existing working-tree changes. | FastAPI; React; document extraction; local embeddings; FAISS/pgvector; lexical reranking; providers; caches; jobs; metadata filters. |
| ConPro PMIS | Branch `conpro-working`, commit `64ae8ba`, plus its pre-existing working-tree changes. | Django/DRF; React/Vite; PostgreSQL configuration; JWT/session authentication; project/record permissions; document revisions; attachments; reporting; audit. |

ConPro's accessible GitHub default branch is `master`, but it differs from the
local working branch. Local source, not an assumption about remote parity, is
the basis of this design. Repository references are root-relative:
`ConPro\...` denotes the ConPro repository; `app\...` denotes the RAG repository.

No production environment, private document content, credential, connection
string, database row, live provider, or deployed permission configuration was
inspected. Role-catalog enablement and optional AI-key availability were not
read from environment files.

The proposed routes, models, event names, flags, synchronization process, and
structured evidence contract below **do not exist merely because this document
names them**. They require separately approved implementation.

### 1.2 Important corrections to avoid false assumptions

- ConPro already has optional AI hooks: scratch-pad summarization and executive
  dashboard questions. These are not the proposed vector/hybrid RAG connector.
- `Project.rag_status` means red/amber/green project health, not
  Retrieval-Augmented Generation.
- ConPro's organization hierarchy and external project parties must not be
  assumed to be independent SaaS tenants. An integration namespace needs an
  explicit deployment/company mapping.
- The RAG application's existing `HybridVectorStore` mirrors storage writes;
  lexical+dense search is still only proposed.
- ConPro accepts file types the current RAG parser cannot process. Indexing
  coverage cannot be equated with document-library coverage.

Evidence: `ConPro\backend\apps\reporting\reports_api.py:247-254`,
`ConPro\backend\apps\reporting\executive.py:506-541`,
`ConPro\backend\apps\scratch\ai.py:28-90`,
`ConPro\backend\apps\projects\models.py:129-207`,
`app\vector_store.py:419-464`, and `app\ingestion.py:32-78`.

## 2. Goals and non-goals

### Goals

1. Answer project-document and permitted record questions with traceable,
   revision-specific evidence.
2. Recover exact construction references and semantically related language using
   independent lexical and dense retrieval.
3. Respect the same project, module, record, company, confidentiality, and
   field-level restrictions as ConPro, including permission changes.
4. Keep ConPro authoritative for records, workflow states, calculations,
   identity, file downloads, and permission decisions.
5. Reuse the existing RAG service, parsers, embeddings, and approved backend
   without creating a replacement application.
6. Keep the integration and hybrid retrieval opt-in, measurable, and reversible.
7. Preserve existing ConPro and RAG behavior when integration is disabled.

### Non-goals

The assistant does not approve submittals, certify payments, alter contracts,
issue drawings, close incidents, publish reports, execute arbitrary SQL,
follow arbitrary URLs, or perform autonomous writes. Its output is assistance,
not a contractual instruction, approval, engineering certification, legal
decision, or substitute for the official record.

No new frontend design, local generative model, knowledge graph, multi-agent
framework, or managed search platform is required for the initial proposal.
Future agentic work requires a separate decision.

## 3. Existing integration surfaces

### 3.1 ConPro: source-of-truth and policy surfaces

| Surface | Verified implementation | Integration implication |
|---|---|---|
| Authentication | Audited JWT/session authentication; token obtain/refresh/blacklist routes. | ConPro authenticates users. RAG browser demo identity must not replace it. |
| Project visibility | `visible_project_ids`, `require_project_access`, `ProjectScopeFilterBackend`. | Resolve project scope on the server before search, ranking, counts, or export. |
| Record permissions | `RoleScopedPermission`; optional published role-catalog `filter_records`/`allows`. | Reuse effective module/action/object policy; global role rank alone is insufficient. |
| Documents | Folder-owned `Document`, controlled metadata/confidentiality, versioned `DocumentVersion`, current-version pointer. | Preserve project, document, version, status, and source links independently. |
| File downloads | Document-version and attachment download actions. | Evidence opens through protected ConPro endpoints, not raw storage URLs. |
| Attachments | Generic parent relations plus daily-report/QC/incident visibility handling. | File access follows its parent record and applicable restrictions. |
| Incidents | Row visibility plus separate restricted-section duties. | Exclude sensitive sections from the initial corpus; administrator status alone does not grant those sections. |
| Reporting | Executive/builder/report snapshot APIs and existing calculations. | Live figures come from approved reporting code, not LLM arithmetic or stale chunk text. |
| Audit | `record_event` and existing audit records. | Record approved integration events using the existing audit mechanism, without logging secret/source contents. |
| Frontend API client | Existing JWT fetch/refresh wrapper. | A future approved UI hook should use this client, not a second login flow. |

Key references:

- `ConPro\backend\config\urls.py:8-29`
- `ConPro\backend\config\settings.py:138-174`
- `ConPro\backend\apps\accounts\scoping.py:24-115`
- `ConPro\backend\apps\accounts\permissions.py:50-184`
- `ConPro\backend\apps\accounts\role_policy.py:417-479`
- `ConPro\backend\apps\documents\models.py:168-276`
- `ConPro\backend\apps\documents\views.py:31-61,418-436`
- `ConPro\backend\apps\attachments\views.py:28-126`
- `ConPro\backend\apps\incidents\access.py:1-84`
- `ConPro\backend\apps\audit\models.py:355-399`
- `ConPro\frontend\src\api.js:1-83`

These are inspected source contracts, not proof that every deployed policy
combination has been tested.

### 3.2 Existing ConPro AI must remain intact

`POST /api/reporting/executive/ask/` already builds a permission-aware facts
payload and uses an optional provider hook. It returns statements/links and
filters unknown record references and numerical tokens.

`apps.scratch.ai` uses an Anthropic-Messages-compatible HTTP interface when its
settings are configured. Scratch summarization has its own task/risk/note shape.
Whether these hooks are active in a deployment was not verified.

Do not silently redirect either interface to `/ask`: the provider and response
contracts differ, and the executive numerical/reference checks must be
preserved. Any future reuse of the existing question affordance is an explicit
adapter decision with compatibility tests, not a replacement in this document.

Evidence: `ConPro\backend\apps\reporting\executive.py:506-541`,
`ConPro\backend\apps\scratch\ai.py:42-90`,
`ConPro\backend\apps\scratch\views.py:63-77`,
`ConPro\frontend\src\api.js:707`.

### 3.3 RAG: reusable components and current gaps

Existing public routes include `/upload`, `/upload-google-doc`,
`/upload-sharepoint`, `/ingest-database`, `/ask`, and job/metrics/feedback routes.
The ingestion path currently copies only the standard scope/metadata fields.
`QuestionRequest` has equality filters; `AnswerResponse` has answer and
question_domain, not a validated structured source list.

Therefore a naive proxy from ConPro to the current `/ask` is **not an acceptable
production integration**. It cannot express all authorized source/version sets,
field projections, permission epochs, or validated citation contracts.

Prerequisites from the hybrid proposal still apply: cache identity/filter fixes,
genuine candidate IDs/metadata, safe staging, atomic replacement, correct async
completion, scoped service authentication, and complete backend filtering.

Evidence: `app\main.py:173-239,458-485`, `app\schemas.py:19-46`,
`app\rag.py:542-552,634-698`, `app\vector_store.py:546-575`.

## 4. Recommended logical architecture

```text
Existing ConPro browser/session
             |
Existing ConPro Django API
  authenticate -> authorize project/module/record/field
             |
Proposed opt-in integration adapter within ConPro
  approved corpus selection + short-lived authorized scope
             |
Private authenticated service-to-service boundary
             |
Existing RAG FastAPI service + proposed integration contract
  verify scope -> dense and lexical retrieval -> RRF
             |
Authorized, current, bounded evidence
             |
Existing configured inference/provider
             |
Validated answer/source mapping
             |
ConPro rechecks evidence permissions/version freshness
             |
Answer and protected ConPro source links
```

Separate indexing path:

```text
ConPro authorized export/synchronization adapter
  approved sources -> versioned manifest + safe projection/file
             |
Proposed durable sync state/outbox and retry handling
             |
RAG parse/chunk/embed -> dense index + lexical index
             |
Atomic corpus generation publication
             |
ConPro integration status/audit
```

These are logical responsibilities. The adapter can initially be a small
module inside the existing Django backend; it does not require a new standalone
project or a replacement PMIS.

Recommended pilot backend: pgvector plus native PostgreSQL full-text retrieval.
Keep the RAG corpus logically separated from the authoritative ConPro tables,
preferably in its existing RAG database with a dedicated restricted role.
Using the same PostgreSQL server is an operational option, not permission to
share writable application credentials or mix business tables.

FAISS plus scoped BM25 remains a local/testing option as in the hybrid proposal.
It is not suitable for shared-worker persistence without additional work.
PostgreSQL native full-text ranking is not BM25.

## 5. Proposed use cases and corpus policy

| Use case | Proposed evidence | Conditions and exclusions |
|---|---|---|
| Locate a specification/drawing requirement | Approved/current controlled documents, revision metadata, extracted pages. | Exact document/spec references plus semantic search; page-aware citations. Drawing geometry/CAD reasoning is not supported by current parsing. |
| Explain an RFI or submittal history | Authorized record summary, decisions/revisions, permitted attachments. | Preserve status/revision and distinguish pending review from approval. |
| Compare revisions | Two explicitly selected, authorized document versions. | Never silently compare only the newest chunks; both versions need source identities. |
| Explain a reported schedule/cost issue | Approved reporting output plus supporting project records. | Live calculations from ConPro; index text is historical evidence, not a current ledger. |
| Summarize permitted QC/NCR findings | Safe record projection and authorized attachments. | Module/record/company restrictions; no personal or restricted incident sections in the pilot. |
| Answer project-wide document questions | Authorized document/version subset within one project. | No default cross-project or company-wide search; portfolio access is a separate scope decision. |

### Initial corpus recommendation

Start with a small, explicitly selected set of **normal-confidentiality,
current, approved or issued controlled documents** in one pilot project.
List the admitted status values in the adapter policy; do not infer eligibility
from a display label or directory.

Exclude confidential/restricted documents, incident personal sections, scratch
pads, private spreadsheets, audit/network details, draft daily reports, public
sharing links, and unapproved unsupported files initially. Broader ingestion is
not needed to demonstrate hybrid retrieval.

ConPro can store arbitrary document types, while RAG currently supports PDF,
DOCX, TXT, and selected image OCR. Unsupported formats receive an explicit
not-indexed status. PDF drawings may yield incomplete text; there is no verified
CAD/BIM, table, or scanned-PDF understanding to claim.

Do not use the existing `/ingest-database` with unrestricted ConPro table access.
Structured records should use versioned, allowlisted ConPro serializers/export
functions that apply field policy before indexing.

## 6. Source identity, metadata, and revision handling

### 6.1 Proposed field mapping

| Integration field | ConPro origin | RAG treatment |
|---|---|---|
| `tenant_id` | Explicit operator-defined ConPro deployment/company namespace. | Server-derived partition; not user email, user ID, or an assumed OrgUnit tenant. |
| `collection_id` | Canonical project ID. | Stable project namespace, such as `project:<id>`; project code is display metadata. |
| `document_id` | Model label + canonical record ID + source version identity. | Stable scoped source ID; never filename/URL slug identity. |
| `source_system` | Adapter constant. | Proposed `conpro`; browser cannot override it. |
| `source_kind`, `source_record_id` | DocumentVersion/Attachment/allowlisted record kind. | Typed provenance and eligibility policy. |
| `source_version_id`, `revision_number` | Version PK/number or explicit record revision/snapshot. | Exact evidence version; current pointer tracked separately. |
| `source_title`, `reference_number` | Authorized document/record labels. | Display metadata and exact-term retrieval. |
| `status`, `confidentiality` | Controlled document/record fields. | Corpus policy plus query-time authorization; not merely prompt instructions. |
| `updated_at`, `indexed_at`, `content_hash` | Source timestamps and computed digest. | Freshness, deduplication, idempotency, reconciliation. |
| `page`, `section`, `start_offset`, `end_offset` | Parser-derived location where available. | Validated citation locator; unavailable values remain absent. |
| `projection_version`, `policy_revision` | Proposed export/policy version. | Avoid serving a broader or outdated field projection. |
| `source_locator` | Typed ConPro source identity. | ConPro constructs protected URLs; no raw storage path/token/provider URL. |

Most added fields are **proposed metadata extensions**, not fields currently
accepted/preserved by the RAG ingestion endpoints.

The canonical project/document/version key should be stable under filename
renames. Keep identical text in separate source records as distinct provenance.
Deduplicate content storage only if the separate authorization/source mappings
remain intact.

### 6.2 Revision semantics

ConPro's `current_version` pointer identifies the latest uploaded revision, not
by itself the approved, effective, or issued contractual revision. The adapter
must reconcile that pointer with workflow/review/issue/effective-date state.
DocumentVersion is intended as append-only file history; test that invariant
through the supported API rather than assuming a database-level immutable row.

- Default document search considers only eligible current revisions.
- Explicit historical comparison retrieves the requested authorized versions,
  clearly labeled as historical; superseded content never masquerades as current.
- Uploading a new revision queues indexing, but publication occurs only after
  extraction, both indexes, and metadata are ready.
- During a pending current revision, do not label the previous indexed version
  current. Suppress it or clearly offer an explicit historical answer.
- Withdrawn/deleted/ineligible sources are tombstoned and excluded immediately
  from authorization, then removed from derived indexes/caches under policy.
- A source version change and corpus generation bump must be atomic from the
  query reader's perspective.

For attachments without a version model, immutable attachment identity plus
content digest/projection version identifies evidence. Parent status and access
changes still invalidate eligibility.

## 7. Authorization and information-flow contract

### 7.1 ConPro remains the authority

The integration must reuse:

1. Account active/session checks and applicable ethics acknowledgement policy.
2. Project visibility, including expiring assignments and hierarchy oversight.
3. Module/action and published-role record rules when that mode is active.
4. Document confidentiality/uploader rules and record-specific visibility.
5. Field-level restrictions and approved external-processing/export policy.

Do not assume a PM, administrator, program user, or project member can see every
field/file. Incident restricted sections are an explicit counterexample.
UI hiding, prompt text, metadata tags, and vector similarity are not authorization.

### 7.2 Proposed query-time authorization boundary

Before either retrieval branch:

- ConPro resolves the requested project and eligible source/version/projection
  set for the authenticated caller.
- It issues a short-lived authenticated scope referencing that set or a server
  policy snapshot. Large sets may use a scoped handle rather than a huge request.
- The RAG service verifies issuer/audience/expiry/request binding and its own
  service credential, then enforces the authorized predicate in both branches.
- Scoring, fusion, counts, snippets, and provider context must not include
  disallowed records. Filtering only the final top five is insufficient.
- Immediately before dispatching source text to the provider and before
  returning an answer, revalidate applicable permission/source generations.
- Any permission change or mismatch invalidates the pending result; discard and
  retry safely or return an explicit unavailable/stale status.

This requires an extension beyond current equality filters. A source-ID set or
policy-handle mechanism is **not already implemented**.

A service credential grants service access, not blanket user document access.
Do not forward the browser's refresh token or expose service credentials to the
browser. Select mTLS or an established short-lived service-token mechanism during
implementation review; do not invent ad-hoc cryptography.

### 7.3 Field-level and provider disclosure

Only approved safe projections enter the pilot corpus. Later field-restricted
records require separately authorized projection variants or equivalent enforced
field policy before chunking/retrieval; a privileged full record must not enter a
general shared text index.

External processing is a separate policy decision from view/download access.
ConPro must approve which classifications/projects may be sent to each provider.
The RAG `auto` mode currently submits prompts to two providers; do not use it for
ConPro content unless both processors are approved. No provider choice is
changed by this document.

Revocation cannot recall text already transmitted to a provider. Minimize that
window, document processor retention/residency, and validate permissions at the
point of dispatch. Embeddings, lexical tokens, snippets, answers, and logs are
derived sensitive data too.

Public expiring share tokens are not a corpus-wide authorization mechanism.
Do not index or place those tokens in citations.

## 8. Synchronization and indexing lifecycle

### 8.1 Proposed mechanism

Use an approved ConPro export/sync adapter, not an unrestricted database reader.
For a pilot, a bounded manual/scheduled command can synchronize the selected
project. Before production, persist synchronization state and committed changes
in the existing database using an outbox or equivalent reliable mechanism.

New durable state is a future schema addition requiring review. The current
RAG in-memory queue alone cannot provide cross-worker job lookup, durable retries,
or permission-change delivery guarantees.

### 8.2 Proposed event handling

| Source event | Required integration behavior |
|---|---|
| New eligible document/version | Validate type/size/policy; index version; publish only after both indexes succeed. |
| Changed safe structured record | Generate approved field projection; upsert by source/version/hash; refresh evidence generation. |
| Current revision changes | Make prior version historical; do not claim pending new version is indexed. |
| Status/confidentiality changes | Re-evaluate eligibility and invalidate source caches; authorization applies immediately. |
| Role/membership/record-sharing change | Bump policy generation, expire authorized scopes and cached answers; recompute visibility. |
| Delete/withdraw/revoke | Deny retrieval immediately; tombstone derived evidence and reconcile removal. |
| Lost/duplicated event or worker restart | Durable checkpoint, idempotent replay, and periodic manifest reconciliation. |

Idempotency key: integration namespace + source identity + source version +
content/projection digest. Out-of-order events must not overwrite a newer version
or undo a tombstone. Apply per-source ordering/generation checks.

Use explicit statuses: queued, indexing, ready, unsupported, failed, stale,
revoked. "Accepted" is not "ready." Expose sanitized error codes and authorized
status; do not leak parser stack traces or record existence to other users.

Avoid a new broker unless backlog/reliability requirements justify it.
A database-backed scheduler/worker can be the first production option if it
meets the agreed delivery and concurrency guarantees.

## 9. Hybrid query and evidence flow

### 9.1 Document questions

1. ConPro authenticates caller, validates the question and selected project,
   and constructs an authorized current-source scope.
2. The RAG service constructs a mode-aware cache identity using scope/policy
   generation, corpus generation, query text, model, and ranking settings.
3. Dense retrieval finds semantic candidates; independent lexical retrieval
   finds exact references/spec terms under the same authorized predicate.
4. RRF combines genuine source identities using 1-based ranks. Initially use
   the hybrid proposal's bounded pools, equal weights, and experimental `k=60`.
5. Select the bounded context. Do not blindly rerun lexical sorting as primary
   order after fusion and erase the dense contribution.
6. Existing relevance checks/prompt/provider are reused under the approved
   integration contract, with untrusted source instructions ignored.
7. Validate CTX/source IDs, version/locator membership, and relevant factual
   support. Unsupported material leads to abstention, not invented evidence.
8. ConPro rechecks permissions/version freshness, constructs protected source
   links, records a minimal audit event, and returns the result.

The hybrid flag remains off by default. Dense-only mode still requires the same
integration authorization/evidence safeguards; disabling hybrid is not a
security rollback.

### 9.2 Structured reporting and numerical answers

Use ConPro's approved reporting calculations or an allowlisted live fact
projection for cost, certification totals, schedule metrics, and counts.
Document chunks can explain context or cite a historical issued report, but
must not be presented as the current authoritative figure.

Each numerical fact needs units/currency, effective period, source definition,
and `as_of`. Preserve the existing executive reference/number checks when using
that surface; membership of a numeric token in facts is not full verification
of calculation or meaning.

The model may explain supplied results. It must not generate executable SQL,
run arbitrary Python, change figures, or invent aggregation formulas. A later
approved adapter can combine live facts with authorized document evidence, with
both evidence types labeled distinctly.

## 10. Proposed API contracts

**This section names new design interfaces, not existing endpoints.**
Final names and schemas require implementation approval.

### 10.1 ConPro-facing adapter

Proposed example: `POST /api/ai/ask/`

Request fields: question, selected project, optional authorized source reference,
and optional explicit historical-version selection. The server derives identity,
tenant/collection, permissions, retrieval mode, and processing policy.

Do not accept user-supplied service URLs, SQL, unrestricted source IDs, arbitrary
tenant scope, or provider credentials.

Proposed response fields:

| Field | Purpose |
|---|---|
| `status` | answered, abstained, unavailable, or stale; not generic success for every outcome. |
| `answer` | Compatible readable answer text. |
| `question_domain` | Existing RAG classifier output where appropriate. |
| `sources` | Validated typed source/version/location/authorized protected link records. |
| `as_of`, `corpus_generation` | Evidence freshness; not proof the PMIS has no newer data. |
| `limitations` | Missing formats, incomplete scope, unsupported sections, or stale history. |
| `request_id` | Correlation across ConPro, sync, RAG, and approved provider telemetry. |

For an unavailable project/record, follow ConPro's non-disclosing visibility
behavior. Use the repository's authentication/error convention for unauthorized
sessions; return bounded sanitized provider/index errors separately from
ordinary abstention.

### 10.2 Private RAG integration boundary

Proposed internal operations:

- Source manifest/upsert and eligible safe file/projection ingestion.
- Source tombstone/deletion and generation synchronization.
- Authorized query with scope handle, policy/corpus versions, and mode.
- Authorized indexing status/readiness.

These can be additive private routes in the existing FastAPI app. They must be
authenticated and inaccessible as a browser permission bypass. Existing generic
upload/SQL/ask routes cannot remain publicly usable against the ConPro corpus
without equivalent guards.

Version the request/response contract. Hybrid mode must fail clearly if an older
retrieval service cannot enforce authorized source sets or preserve candidates.
No broad TypeError retry may discard filters.

### 10.3 Current reusable download endpoints

Verified current routes:

- `GET /api/documents/document-versions/{id}/download/`
- `GET /api/attachments/attachments/{id}/download/`
- `GET /api/documents/documents/{id}/`

Routes are derived from `ConPro\backend\config\urls.py:21,27`,
`ConPro\backend\apps\documents\urls.py:6-14`,
`ConPro\backend\apps\documents\views.py:418-436`, and
`ConPro\backend\apps\attachments\urls.py:6`.

Browser access must still pass ConPro's current policy; a citation is not a
preauthorized static blob link. Deep-link paths should be constructed by the
existing frontend/router contract during implementation, not guessed from model
names.

## 11. Citations, cache, and audit requirements

### 11.1 Citation contract

Each source maps a claim/context block to deployment/project, source type/ID,
exact version, approved title/reference, and available page/section/offset.
ConPro supplies the final protected locator.

Never invent pages for parsers that did not preserve them. CTX identifiers are
request-local; persistent evidence identity is separate. A References string
from the model is not trusted without membership validation.

Historical versus current status and extraction limitations must be visible.
Do not return snippets, titles, links, or even source counts for unauthorized
sources.

### 11.2 Cache rules

Keys must include complete authorized scope/projection identity, effective user
policy or equivalent visibility fingerprint, project, permission generation,
corpus generation, query text, mode, and relevant model/prompt/ranking settings.

Never share a cached answer merely because users share a project or role name.
Cache lookup still requires current authorization and source-version validation.
Membership expiry, policy changes, revoked sources, and new revisions invalidate
answers before use.

Fix the existing advanced-filter and independent-store cache defects before
integration. A 30-minute TTL is not a revocation policy. Multi-worker use needs
shared generation/invalidation rather than process-local revisions.

### 11.3 Minimal audit evidence

Proposed event names: `AI_QUERY_REQUESTED`, `AI_QUERY_COMPLETED`,
`AI_QUERY_DENIED`, `AI_INDEX_SYNC`, and `AI_SOURCE_REVOKED`.
These are proposed additions to ConPro's audit-event vocabulary. They have not
been implemented and require review and approval before registration.

Reuse ConPro `record_event` after approval. Record actor/project, request ID,
outcome, source IDs/versions where policy permits, processing mode, safe timing,
and policy/corpus generations. Do not store raw confidential prompts, source
bodies, tokens, or provider secrets in generic audit changes/comments.

**Approved standalone RAG retention policy (implemented separately):** save only
on explicit request in a private answer store, not in generic audit changes.
Maximum/default retention is 30 days. Only the owner with current project access
may read an answer; administrators have no ownership bypass. Expired records are
deleted; observed policy or local-index changes scrub the complete question and
answer, leaving restricted metadata until expiry. Later reads never return
scrubbed content. Owner deletion remains possible after project revocation.
Storage must be configured outside the repository with operator-managed ACLs.

This implementation is intentionally local-FAISS-only: an index restart or any
observed policy/index change invalidates saved content conservatively. It cannot
verify external ConPro document ACLs or shared-database generations. Before the
ConPro connector exposes retained answers, bind each answer to all supporting
source/version identities and durable revocation generations; recheck current
ConPro source/export permissions on every later read. If any dependency is
revoked, changed, missing or unverifiable, withhold the entire question/answer and
redact it rather than return a partial answer. No stale-permission fallback.

Expiry is enforced on access, with physical cleanup at startup/every 60 seconds
while RAG runs. Storage snapshots/backups, provider retention, delivered chat and
user copies need separate rules; redaction cannot recall already disclosed text.
See `SECURITY_AND_RELIABILITY.md` in the RAG repository for endpoints, limits,
configuration and the unobserved-revocation limitation.

## 12. Deployment and operation

Keep the ConPro database and workflows authoritative. The RAG index is a
rebuildable derived corpus, not a replacement backup or system of record.

Proposed operator flags, **not implemented**:

```text
CONPRO_RAG_ENABLED=false
HYBRID_RETRIEVAL_ENABLED=false
```

The flags are independent: the first gates integration; the second gates hybrid
search inside a correctly authorized integration. Existing ConPro scratch and
executive AI settings retain their current meaning.

Deployment requirements before a production pilot:

- Private TLS-protected service communication and least-privilege credentials.
- Explicit approved provider/data-classification policy.
- Persisted pgvector/lexical data, corpus generations, and sync status.
- Readiness that checks selected-backend/schema/contract availability.
- Bounded uploads, extraction, candidate pools, prompts, deadlines, and quotas.
- Monitoring of sync lag, unsupported/failed sources, authorization denials,
  abstention, retrieval latency, provider errors, and evidence validity.
- Backup/rebuild procedures for manifests and a tested corpus-reconciliation
  process; no ConPro business-table write access from the RAG role.

Both applications default to ports 8000/5173 in local development. They cannot
both occupy those same addresses simultaneously. Future integration setup must
assign separate loopback ports or use container-network service names. No port
or server was changed for this document.

## 13. Phased delivery plan

| Phase | Proposed scope | Exit gate |
|---|---|---|
| I0: contract and policy review | Confirm namespace, pilot corpus/statuses, providers, permission adapters, retention, and separate service addresses. | Owners approve source eligibility and authorization matrix. |
| I1: prerequisites | RAG cache/result identity fixes; safe staging; atomic replacement; service authentication; authorized source filtering; durable/versioned contract. | Isolation and failure tests pass; generic routes cannot bypass ConPro policy. |
| I2: limited corpus pilot | One project, eligible normal documents, manifest/safe file export, explicit ready/unsupported/failed status. | Revision freshness, idempotency, tombstone, and reconstruction tests pass. |
| I3: opt-in hybrid queries | Dense + native PG lexical search + bounded RRF, evidence validation, current source links. | Retrieval quality/latency gates pass with zero unauthorized evidence. |
| I4: approved records/live facts | RFIs/submittals/report projections, permitted attachments, live deterministic reporting facts. | Module/record/field policies and numerical/source contracts pass. |
| I5: operational rollout | Durable synchronization, shared invalidation, monitoring, audit, rollback, optional existing-UI adapter. | Multi-worker/revocation/recovery and compatibility tests pass. |

Reusing existing ConPro UI affordances or adding a button/panel is a later,
separately approved UI task. This document makes no such change and does not
require a redesign.

Bounded agentic retrieval remains optional after measured evidence of unmet
multi-hop needs. Any future agent retains the same authorization and read-only
tool boundaries; it cannot circumvent ConPro workflows.

## 14. Acceptance tests and review targets

These tests are proposed. No integration implementation or ConPro test suite was
executed for this documentation-only task.

### Mandatory security and correctness matrix

- Nonmember cannot retrieve, rank, count, cite, or cache another project's data.
- Effective published-role view/export and record/company rules are honored.
- Confidential/restricted document access is not inferred from project membership.
- Incident restricted fields stay unavailable even to administrators without the
  required duties; pilot exclusion is verified before indexing.
- Private/draft daily-report/QC/attachment access follows the parent record.
- Revoked/expired account/project/role permissions reject new and cached results.
- Permission/source changes during retrieval/inference invalidate the answer.
- Dense and lexical branches, local/service paths, and all caches enforce the
  same authorized source/projection set.
- Public share token or direct RAG route cannot become an integration bypass.
- Unsupported files, corrupt documents, oversize input, missing blobs, and
  provider failures have explicit authorized status without secret disclosure.

### Synchronization and evidence matrix

- Same filename in different projects/documents retains distinct identities.
- Duplicated/out-of-order events and retries do not restore revoked content.
- New revisions are not ready until both indexes and metadata publish.
- Current, superseded, and explicitly historical evidence remain distinguishable.
- Every returned citation belongs to authorized retained context and resolves
  through a protected ConPro locator; stale/deleted evidence is rejected.
- Provider payloads contain only approved fields/classes and exact evidence.
- Live numerical answers preserve ConPro definitions, units, periods, and source
  links; stale reports are labeled historical.

### Proposed evaluation targets

Use a versioned non-sensitive pilot corpus with exact spec/document/RFI numbers,
semantic paraphrases, unsupported questions, revision changes, and permission
variants. Compare dense-only, lexical-only, and fused retrieval.

Initial targets inherited from the hybrid proposal:

- Zero unauthorized candidates/context/citations/cache hits in the regression
  matrix. Access correctness is a hard gate, not an average metric.
- Macro Recall@5 no worse than the approved dense baseline; target at least five
  percentage points improvement on the exact-reference subset.
- Warm retrieval p95 initially no more than 1.25 times baseline on identical
  hardware, corpus, and concurrency.
- Every structured citation resolves to authorized exact evidence; semantic
  claim support is evaluated separately, not inferred from source-ID validity.
- Agree a synchronization freshness objective before deployment; do not invent
  an achieved lag or availability SLO.

Quality/latency figures are proposals, not measured integration results.

### Compatibility and rollback

Flag-off tests must preserve existing ConPro workflows, reporting AI hooks,
authentication, downloads, and RAG standalone behavior.

Disable integration to stop new AI requests/synchronization without changing
ConPro records. Disable hybrid to restore authorized dense retrieval only.
Drain/cancel pending jobs and expire scope handles as appropriate; do not remove
authentication or re-enable unsafe generic corpus access.

Retain derived data only under the approved retention policy; permission denial
applies immediately even when physical deletion is asynchronous. A rollback must
not delete source documents, revisions, financial records, or audit history.

## 15. Review decisions and deliverables

Before implementation, confirm:

1. Pilot project/status selection and normal-only versus wider corpus policy.
2. Deployment/company namespace and project scope; no inferred multi-tenancy.
3. Canonical ConPro authorization/export adapters and revocation guarantees.
4. Provider approval, retention/residency, and external-processing permissions.
5. Supported source formats and provenance/version contract.
6. Durable synchronization mechanism, schema ownership, and service isolation.
7. Whether any existing question UI is later reused, and its unchanged response
   compatibility requirements.
8. Evaluation dataset, thresholds, sync freshness, and operational rollback.

Deliverables for this task:

- `CONPRO_PMIS_RAG_INTEGRATION.md`: editable design and review decisions.
- `CONPRO_PMIS_RAG_INTEGRATION.pdf`: searchable review/comment copy.

Related source documents:

- RAG repository root `RAG_HYBRID_ARCHITECTURE_PROPOSAL.md`: hybrid retrieval
  and phased evolution.
- RAG repository root `RAG_CODEBASE_ANALYSIS.md`: verified RAG behavior and
  prerequisite gaps.
- ConPro Document Control, role/permission, reporting, and Activity documentation,
  interpreted alongside the source references above.

**Implementation remains unapproved and unperformed.** Creating this document
and PDF does not enable a connector, alter either existing application, export
PMIS content, configure a provider, or commit/push changes.
