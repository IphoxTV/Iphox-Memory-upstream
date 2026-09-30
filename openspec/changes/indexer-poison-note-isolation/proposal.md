## Why

GitHub #308: two notes containing raw NUL bytes (`\x00`) wedged a user's indexer for 8.5 days. PostgreSQL `text` cannot hold 0x00, so the keyword-vector UPDATE raised `CharacterNotInRepertoireError`; the retreat in `write_tsvector_bounded` only addresses *size*, so it re-raised at the floor, the pass's single transaction rolled back, and every tick re-upserted and re-vectorised all ~5,000 notes and threw the work away — 2,091 times, ~650 GB/day of writes, no new note indexed or embedded, while `/health` answered `ok` and the only signal was a CRITICAL log line.

This is the third route to the same failure class — one note takes indexing down for its whole owner (#126 title, #154 non-finite frontmatter, now NUL). The previous two were fixed value-by-value at the boundary that broke. That fixes the route, not the class, and the class stays silent. NUL is increasingly likely as vaults are written by agents (the reporter's notes were agent-written documentation of code using `\0` as a delimiter), and nothing in `create_note` / `edit_note` rejects it.

## What Changes

- **NUL is removed from note text at the indexer's single decode point** (`read_note_at`), before hashing, so every derived column (tsvector, title, tags, links, chunk text) and every re-verifying reader (embed backlog, reconciliation, link backfill, tsvector rebuild) sees the same NUL-free text and the same hash. The file on disk is never modified. A WARNING names the file.
- **NUL is removed from frontmatter-derived strings** (title, tags, JSONB keys and values) at the indexer's JSON boundary, because YAML's `"\0"` escape produces a NUL from NUL-free bytes.
- **A note that still fails at a per-note database boundary is quarantined, not fatal to the pass.** A floor failure of the keyword-vector build, or a data-class error on that note's row in the batch upsert, aborts the attempt, records `(owner, path, content_hash)` in an in-process quarantine, and re-runs the pass without that note (bounded retries per tick). The quarantined note keeps its previous row untouched, so no committed hash ever sits beside a stale derived row; it is retried automatically when its content hash changes. **Behaviour change:** the incremental-pass floor-failure scenario no longer aborts the pass (MODIFIED requirement).
- **Indexer failure is visible to monitoring.** Consecutive failed passes are counted per scope in both single- and multi-user loops (today the multi-user loop never counts). `/health` gains an `indexer` object and reports top-level `status: "degraded"` once any scope reaches the threshold or any note is quarantined. HTTP status stays 200 — a liveness restart cannot fix vault content. `/health` carries counts only: no paths, no error text, no user identity.
- The two real-PostgreSQL tests that use a NUL note as their "floor failure" fixture move to a synthetic floor failure; new tests prove a NUL note indexes and a poison note is quarantined while the rest commits.

Out of scope (recorded in design as a follow-up decision for the owner): refusing NUL in `create_note` / `edit_note` / `write_file` content.

## Capabilities

### New Capabilities
<!-- none -->

### Modified Capabilities
- `index-integrity`: NUL-free derivation of every indexed value; per-note quarantine for poison notes; the incremental floor-failure scenario changes from "abort the pass" to "quarantine the note, commit the rest".
- `panel-ops-health`: `/health` reports indexer degradation (consecutive failures, quarantined notes) without disclosing paths or tenants.

## Impact

- `src/services/indexer.py`: `read_note_at`, `_note_title`, `extract_tags`, `_jsonb_value`, `write_tsvector_bounded` call site in the incremental pass, the batch upsert, `_index_pass_once` / `run_indexer_loop` failure accounting, a new quarantine registry and failure-state accessors.
- `src/main.py`: `/health` response body (additive fields; `status` can now be `"degraded"`).
- `src/config.py`: `INDEXER_DEGRADED_AFTER_FAILURES` (default 3), `INDEXER_QUARANTINE_RETRIES_PER_TICK` (default 5).
- Tests: `tests/integration/test_tsvector_bounded_pg.py` fixtures; new unit and integration tests.
- Docs: `docs/architecture/indexing-and-embeddings.md` (the floor-failure bullet and the "retries next tick" statement), `README.md` / `DEPLOYMENT.md` monitoring note for `/health`.
- No migration. No change to write tools or to note bytes on disk.
