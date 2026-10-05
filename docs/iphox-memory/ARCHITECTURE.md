# Iphox Memory architecture

Iphox Memory is a web-first durable memory layer for ChatGPT and other MCP clients.
It is built on the upstream Obsidian MCP server, but keeps **Markdown as the canonical
source of truth** and treats PostgreSQL/pgvector indexes as disposable derivatives.

## Design goals

1. Human-auditable memory: every durable item is a normal Markdown note.
2. Shared memory across ChatGPT Web sessions and devices through remote HTTPS MCP.
3. No "save everything" behavior. Durable writes pass a promotion gate.
4. Time-aware truth: active, stale, superseded and archived are distinct states.
5. Provenance: volatile/project facts can carry source, source reference and verification time.
6. Small context: retrieval returns a bounded task-specific context pack, not the vault.
7. Recovery: indexes can be rebuilt from Markdown without losing canonical memory.
8. Privacy boundary: secrets and raw credentials never belong in the vault.

## Layers

```text
ChatGPT Web / Iphox App Engineering
              |
              v
       HTTPS MCP + OAuth
              |
              v
   Iphox Memory policy layer
   - promotion gate
   - lifecycle / supersession
   - project/profile/handoff semantics
   - deterministic pre-ranking
              |
              v
      upstream Obsidian MCP
   - note CRUD
   - FTS
   - embeddings / semantic search
   - wikilink graph
   - OAuth / API keys / audit
              |
       +------+------+
       |             |
       v             v
 Markdown vault   PostgreSQL/pgvector
 canonical        derived index
```

## Memory lifecycle

```text
candidate -> active -> stale -> active
                    \-> superseded -> archived
          \------------------------> archived
```

`superseded` never means deleted. The old note remains inspectable and points to the
replacement. Retrieval excludes superseded/archived notes from current context by default.

## Durable memory types

- `profile`: durable non-sensitive profile context.
- `project`: current project state or project-level context.
- `decision`: a decision and why it was made.
- `fact`: a fact with provenance when appropriate.
- `preference`: a stable preference.
- `handoff`: compact continuation state between sessions.
- `lesson`: reusable learning from completed work.
- `rule`: hard working constraint.
- `session`: chronological trace; not promoted to durable memory by default.

## Canonical note metadata

```yaml
memory_id: fiber/ui-linux-rule
type: rule
status: active
verification: verified
project: FIBER
importance: 0.95
confidence: 1.0
created_at: 2026-10-06T00:00:00Z
updated_at: 2026-10-06T00:00:00Z
verified_at: 2026-10-06T00:00:00Z
source: github
source_ref: abc123
supersedes: []
tags: [ui, linux, imgui]
```

## Retrieval contract

The future high-level `memory_context` operation should combine:

1. exact project / entity match;
2. lifecycle filter (current truth first);
3. hard rules and decisions;
4. recent handoff/project state;
5. full-text and semantic retrieval;
6. wikilink neighborhood;
7. deterministic re-ranking and a strict output budget.

The caller gets a compact context pack with note IDs/provenance so every recalled claim can
be inspected or corrected.

## Promotion contract

The default is **do not promote**. A candidate becomes durable only when at least one strong
signal exists, such as explicit user intent, repeated observation, source verification, or
high-importance decision/rule. Session chatter is never promoted just because it occurred.

## Hosting target

Production is a remote HTTPS deployment so ChatGPT Web can use it with the user's PC off.
Deployment and verification are local/manual for this fork; GitHub Actions are intentionally
not part of the Iphox workflow.
