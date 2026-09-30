## Context

Current state (file:line as of `0bfddc8`):

- Bytes become text in exactly one place, `read_note_at` (`src/services/indexer.py:1527`), UTF-8 strict. Every indexer reader goes through it: the scan via `_read_and_hash` (:1727), and `read_note_beneath` (:1580) for the embed backlog (:4237), reconciliation (:3865), link backfill (:3211) and the tsvector rebuild (:3220). It is indexer-only; no MCP tool reads through it.
- `content_hash` is `sha256` of the decoded text (`_content_hash`, :684). The write-precondition hash is separate and deliberately so (`vault.py:1875`).
- One index pass for one scope is one transaction: generation lock (:2269) → moves → batch upsert (:2616, 100 rows per statement) → tsvectors (:2701, `write_tsvector_bounded`) → deletes → links → provenance stamp → single `commit()` (:2868). "Commit together so a new hash is never paired with stale search data" (:2864).
- `write_tsvector_bounded` (:762) retreats by halving to a 100,000-char floor, each attempt in its own savepoint, and re-raises at the floor. A short note starts below the floor, so a NUL fails on the first attempt and aborts the pass.
- Failure accounting: `consecutive_failures` is a local of `run_indexer_loop` (:6111), incremented only in single-user mode; the multi-user path (`_index_pass_once`, :5990) swallows the error. In single-user mode an index failure also skips `embed_vault` (:6165). `/health` (`src/main.py:776`) returns a static `ok`.
- A pass that aborts leaves the scope due, and `_last_full_hash` (:1905) advances only after a clean committed full-hash pass — so after a restart, every failing tick is a full-hash pass re-reading and re-writing everything. That is the 650 GB/day.
- `tests/integration/test_tsvector_bounded_pg.py:162-214` uses a NUL note as the *fixture* for "the floor fails and the pass aborts with nothing committed".

Constraints carried from `docs/architecture/indexing-and-embeddings.md` that this design must not undo:

- **No skip list that strands a committed `content_hash` beside a stale keyword vector** (doc :260-270; code :777-784).
- **One commit per pass**; never a new hash beside stale derived rows.
- **Never rewrite the note's bytes** to make it indexable; convert at each JSON boundary, not at the parse (#154).
- The full rebuild (`rebuild_tsvectors`) stays atomic and fails loud to the operator.

## Goals / Non-Goals

**Goals:**
- A NUL anywhere in a note — body or YAML-escaped frontmatter — indexes normally.
- A note that fails at a per-note database boundary for *any* reason costs that note, not its owner's whole index, and cannot cause whole-pass rewrite loops.
- A persistently failing indexer, or a quarantined note, is visible on `/health` to an ordinary uptime monitor.

**Non-Goals:**
- Changing the write tools. Refusing NUL in `create_note` / `edit_note` / `write_file` is a separate owner decision (Open Questions).
- Making the full `rebuild_tsvectors` non-atomic. It keeps aborting loudly; with D1 in place, NUL no longer triggers it.
- Isolating failures that are not attributable to one note (database down, lock timeout, provider outage). Those still fail the pass and now count toward degradation.
- A panel UI for the quarantine. It is visible through the run record (D5) the panel already renders; a dedicated view can follow.

## Decisions

### D1. Remove NUL in `read_note_at`, before hashing — and nowhere else in the body path

`read_note_at` returns `text.replace("\x00", "")`, and logs one WARNING per read naming the vault-relative path and the NUL count (never content). Because every reader and re-verifier shares this function, the scan's hash, the embed pass's `StaleCertification` check and the rebuild's certification all compute over the same NUL-free text — so no reader can disagree with another about a hash (a perpetual re-index loop would need *some* reader to strip and another not to). A NUL-free note's text is unchanged, so its hash is unchanged: **no mass re-index on deploy**.

- *Removal vs. replacement with a space / U+FFFD:* removal is what the reporter asked for and what Postgres would do if it could; replacement changes token boundaries in a way that is no more "correct". Removal is chosen, and is the documented behaviour.
- *Strip at each DB boundary instead:* rejected — five-plus boundaries (tsvector, title, tags, links, chunk text), and any one missed is the next #308. The decode point is one line.
- *Hash the raw bytes, strip after:* rejected — the hash must describe what was indexed, and every re-verifier would need the same split.
- The warning fires on each actual read, which after the first pass is at most once per full-hash interval (24 h) per file thanks to the stat shortcut. Acceptable; it is the operator's pointer to the file.

### D2. Remove NUL from frontmatter-derived strings at the indexer's JSON boundary

YAML `"\0"` produces a real NUL from NUL-free bytes, so D1 does not cover it. `_jsonb_value` removes NUL from every string key and value on its existing walk (same place #154 converts non-finite floats; key-collision rule unchanged: first in document order wins); `_note_title` and `extract_tags` remove NUL from their outputs. The parsed mapping `set_frontmatter` re-serialises is **not** touched — the #154 rule.

### D3. Quarantine a poison note by restarting the pass without it

A **poison failure** is a database error raised while writing one identifiable note's derived data whose SQLSTATE is in class 22 (data exception — includes 22021 `character_not_in_repertoire`, 22P02, 22003, 22001, 2200N) or 54000 (`program_limit_exceeded`), at either of two sites:

1. `write_tsvector_bounded` failing at the floor during the **incremental pass** (the rebuild is excluded — it keeps its atomic abort);
2. the **batch upsert** raising such an error. The batch is then re-executed row by row, each row in its own savepoint, to identify the first offending note (the batch is ≤ 100 rows; this cost is paid only on failure).

On a poison failure the pass raises an internal `PoisonNote(owner, rel_path, content_hash, sqlstate)`, the transaction rolls back as today, the note is added to the **quarantine**, and the pass is re-run immediately for the same scope. At most `INDEXER_QUARANTINE_RETRIES_PER_TICK` (default 5) re-runs per scope per tick; exceeding it fails the pass as today (and counts toward D4).

The quarantine is an in-process map keyed by `(owner, rel_path)` holding the `content_hash` that failed, the SQLSTATE and the time. In the pass's classification, a note whose current `content_hash` equals its quarantined hash is **excluded from `to_upsert`** — its existing row (if any) is left exactly as it was: old hash, old tsvector, old links, old embeddings. That is the invariant the "no skip list" rule protects: nothing is committed for the note, so no committed hash sits beside a stale derived row. When the file's content hash changes, the entry no longer matches and the note is tried again (and re-quarantined if it still fails). The entry is removed when the note indexes successfully, is deleted, or its scope is discarded.

- *Why restart instead of a savepoint per note:* the upsert is batched and the tsvector writes run after it in the same transaction, so a per-note savepoint would mean un-batching the upsert on the happy path (perf regression on every pass) or reverting an already-upserted row. Restart costs nothing on the happy path and at most N extra partial passes when a poison note first appears.
- *Why in-process, not a table:* no migration, and a restart re-learns each poison note at the cost of one aborted attempt per note. With D1/D2 no known input reaches this path; it is the backstop for the next unknown one, so its state need not be durable.
- *Quarantine is not a read failure.* The note was read and hashed; it is excluded by decision. It SHALL NOT keep the scope due for a full-hash pass, and it SHALL NOT make a re-derive "incomplete" — otherwise a single quarantined note re-arms the whole-scope rewrite loop through the re-derive path (index-integrity "A re-derive that skipped any file is incomplete…"). The re-derive records completion; the quarantined note is simply absent from the re-derived index until its content changes. That is the declared degradation.
- A quarantined note is logged at ERROR once when quarantined (path, SQLSTATE; no content), not on every pass.

### D4. Count failures per scope in both loops; expose on `/health`

A module-level registry in `indexer.py` holds, per scope (`None` for single-user, `user_id` otherwise): `consecutive_failures`, `last_success_at`, `last_failure_at`. `_index_pass_once` updates it in both modes; the existing CRITICAL log fires once when a scope first reaches `INDEXER_DEGRADED_AFTER_FAILURES` (default 3 — ~18 min at the default interval; the old hard-coded 5 is replaced), not every tick thereafter.

`/health` adds:

```json
"indexer": {"status": "ok" | "degraded",
            "failing_scopes": 0, "max_consecutive_failures": 0,
            "quarantined_notes": 0, "last_success_at": "…" | null}
```

and the top-level `status` becomes `"degraded"` when `failing_scopes > 0` (a scope at or over the threshold) or `quarantined_notes > 0`. It reads in-process state only — it never probes, consistent with the endpoint's docstring. **HTTP stays 200**: the Kubernetes manifests use `/health` for liveness, and a restart loop cannot repair vault content; operators monitor with a keyword/JSON check on `status`. **No paths, error text, SQLSTATEs or user ids** appear: `/health` is unauthenticated and routed publicly, and in multi-user mode a path would disclose another tenant's note names.

### D5. Surface the quarantine where the operator already looks

The pass's `indexer_runs` row records the quarantine in its existing `error` column — `"quarantined N note(s): <path>, …"` (paths capped at 5, then `…`) — so the dashboard strip and health page already show it without a template change. A pass whose only anomaly is a quarantine still commits and still embeds; only the run record and `/health` carry the signal. The CRITICAL "manual intervention" wording is kept for the consecutive-failure case.

### D6. Tests

- The two NUL-fixture integration tests move to a synthetic floor failure (e.g. a monkeypatched `to_tsvector` call raising SQLSTATE 54000 for one note), and assert the new behaviour: the note quarantined, the other notes committed, the note's pre-existing row unchanged.
- New real-Postgres tests: the #308 repro (`hello\x00world`) indexes and is keyword-searchable as `helloworld`; YAML `title: "a\0b"` indexes; a NUL-bearing note embeds (chunk text insert succeeds); a quarantined note is retried after an edit and indexes once fixed; `max retries` exceeded fails the pass.
- Unit tests: `/health` shapes (ok, degraded by failures, degraded by quarantine, no path in body), multi-user failure counting, hash stability for NUL-free notes.

## Risks / Trade-offs

- [A quarantined new note is invisible to search until edited] → it is logged at ERROR, counted on `/health`, named in the run record; with D1/D2 no known input reaches this.
- [Restart repeats up to N partial passes' writes when poison notes first appear] → bounded per tick; subsequent ticks exclude the note up front. Far below today's unbounded loop.
- [A non-note-specific class-22 error mis-attributed to a row] → the per-row replay identifies a row only if that row fails alone; if no single row fails, the error is not a poison failure and the pass fails normally.
- [NUL removal merges tokens: `a\0b` is searchable as `ab`] → declared behaviour; the file keeps its bytes.
- [`/health` degraded does not change HTTP code, so a status-code-only monitor misses it] → documented in DEPLOYMENT.md; changing the code would turn liveness probes into a restart loop.

## Migration Plan

No schema change. Deploy normally. On first pass after deploy, NUL-free notes keep their hashes (no re-index); a previously wedged scope completes its pass, which is one full write of the backlog, then returns to incremental. Rollback: redeploy the previous image — behaviour returns to the pre-change abort.

## Open Questions

- **Owner decision (follow-up, not this change):** should `create_note` / `edit_note` refuse content containing NUL? It would stop agents planting it (the #308 origin) at the cost of a new refusal on the write surface, which is an adversarial-review trigger of its own.
- Codex review: is SQLSTATE class 22 + 54000 the right poison set, or too broad/narrow?
