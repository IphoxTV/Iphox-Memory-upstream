## 1. NUL-free derivation (D1, D2)

- [ ] 1.1 `read_note_at`: remove `\x00` from the decoded text before returning; one WARNING per read with vault-relative path and count, no content
- [ ] 1.2 Confirm (grep) that no writer of `notes_metadata.content_hash` outside the indexer hashes un-stripped text; record the finding in the PR
- [ ] 1.3 `_jsonb_value`: remove `\x00` from string keys and values on the existing walk (first-key-wins collision rule unchanged)
- [ ] 1.4 `_note_title` and `extract_tags`: remove `\x00` from outputs
- [ ] 1.5 Unit tests: NUL-free text and hash unchanged; body NUL removed; YAML-escaped NUL in title/tags/keys removed; `set_frontmatter` round-trip unchanged

## 2. Poison-note quarantine (D3, D5)

- [ ] 2.1 Quarantine registry in `indexer.py` keyed by `(owner, rel_path)` → `(content_hash, sqlstate, at)`, with clear-on-success/delete/discard
- [ ] 2.2 Poison classification helper: SQLSTATE class 22 or 54000, unwrapping SQLAlchemy/asyncpg exceptions
- [ ] 2.3 Incremental pass: floor failure of `write_tsvector_bounded` with a poison SQLSTATE raises `PoisonNote`; the rebuild path is unchanged
- [ ] 2.4 Batch upsert: on a poison-class error, replay the batch row-by-row in savepoints to identify the offender, then raise `PoisonNote`; if no row fails alone, re-raise the original error
- [ ] 2.5 Pass classification excludes a note whose current hash equals its quarantined hash from `to_upsert`, without counting it as a read failure or a re-derive skip
- [ ] 2.6 Re-run loop in `_index_pass_once` bounded by `INDEXER_QUARANTINE_RETRIES_PER_TICK` (config, default 5)
- [ ] 2.7 Run record `error` names quarantined paths (≤ 5, then `…`); one ERROR log per quarantine
- [ ] 2.8 Move the NUL-fixture floor tests in `tests/integration/test_tsvector_bounded_pg.py` to a synthetic 54000 floor failure and assert quarantine semantics
- [ ] 2.9 Integration tests (real Postgres): #308 repro indexes and is searchable; NUL note embeds; poison tsvector note quarantined while others commit; poison upsert row identified; edit clears quarantine; quarantine does not re-arm re-derive/full-hash; retry bound exceeded fails the pass

## 3. Failure accounting and `/health` (D4)

- [ ] 3.1 Per-scope failure registry updated from `_index_pass_once` in both modes; replace the local counter in `run_indexer_loop`
- [ ] 3.2 `INDEXER_DEGRADED_AFTER_FAILURES` (default 3); CRITICAL log once on reaching it, re-armed on success
- [ ] 3.3 `/health`: add `indexer` object and `degraded` top-level status; HTTP 200; no paths/errors/ids; update docstring
- [ ] 3.4 Unit tests: ok, degraded by failures, degraded by quarantine, multi-user counting, body contains no path

## 4. Docs

- [ ] 4.1 `docs/architecture/indexing-and-embeddings.md`: NUL rule, quarantine rule, revised floor-failure bullet, "a quarantine is not a read failure"
- [ ] 4.2 `DEPLOYMENT.md` / `README.md`: monitor `/health` `status` by keyword, not status code; new settings
- [ ] 4.3 `CLAUDE.md` key-decisions line for the quarantine and `/health` degraded

## 5. Gates

- [ ] 5.1 `pytest tests` and `make test-integration` green
- [ ] 5.2 `openspec-verifier` pass; adversarial Codex review (indexing path is a mandatory trigger)
- [ ] 5.3 Deploy; end-to-end: plant a NUL note in the live vault, confirm it indexes, `keyword_search` finds it, `/health` stays ok; remove it
