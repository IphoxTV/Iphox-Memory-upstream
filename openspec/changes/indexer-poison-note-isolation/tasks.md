## 1. NUL-free derivation (D1, D2)

- [ ] 1.1 `read_note_at`: remove `\x00` from the decoded text before returning; one WARNING per read with vault-relative path and count, no content
- [ ] 1.2 `vault.note_title` and `vault.extract_tags` (shared by indexer, `read_note` metadata, `move_note`): remove `\x00` from results
- [ ] 1.3 `_jsonb_value`: remove `\x00` from string keys and values on the existing walk (first-key-wins collision rule unchanged)
- [ ] 1.4 `links.py`: a link whose decoded target/anchor/alias contains `\x00` is not extracted (markdown `%00` and wikilink forms)
- [ ] 1.5 Unit tests: NUL-free text and hash unchanged; body NUL removed; YAML-escaped NUL in title/tags/keys removed on every surface; `[x](bad%00target.md)` yields no link; `set_frontmatter` round-trip unchanged

## 2. Poison-note quarantine (D3, D5)

- [ ] 2.1 Quarantine registry in `indexer.py` keyed by `(owner, rel_path)` → `(content_hash, sqlstate, at)`, with clear-on-success/delete/discard
- [ ] 2.2 Poison classification helper: SQLSTATE class 22 or 54000, unwrapping SQLAlchemy/asyncpg exceptions
- [ ] 2.3 Savepoint every attributable write site (move UPDATE, batch upsert, tsvector floor in the incremental pass, link inserts), `try` outside `begin_nested()`; batch sites replay per row in savepoints to attribute; unattributable → re-raise
- [ ] 2.4 `PoisonNote` → full rollback → re-run from classification; bound `INDEXER_QUARANTINE_RETRIES_PER_TICK` (config, default 5); lives in `index_vault` (or a wrapper every caller uses) so startup, periodic and manual reindex all recover
- [ ] 2.5 Classification: a file whose hash equals its quarantined hash is excluded from upsert and move detection; any existing row at that path is deleted (with embeddings and outgoing links) through the ordinary delete path; not a read failure, not a re-derive skip, does not keep the scope due
- [ ] 2.6 Run record `error` names quarantined paths (≤ 5, then `…`) without the pass counting as failed; one ERROR log per quarantine
- [ ] 2.7 `tests/integration/test_tsvector_bounded_pg.py`: incremental NUL-fixture test → genuine server-side floor failure (temporary trigger) asserting quarantine + rest committed; full-rebuild test (:249-273) keeps whole-rebuild rollback with the synthetic trigger
- [ ] 2.8 Integration tests (real Postgres), per design D6: #308 repro + next tick writes nothing; NUL note embeds; each attributable site (server-side failure on a valid-length move, upsert row, tsvector, link row) after an earlier successful move; indexed+embedded note turned poison is removed, not served stale by either search tool; edit clears quarantine; re-derive with quarantine stamps provenance and next tick re-upserts nothing; retry bound; startup and manual reindex entrypoints

## 3. Failure accounting and `/health` (D4)

- [ ] 3.1 Per-scope registry: index failures, `rederive_incomplete`, embedding failures (from typed `EmbedPassResult` provider failures), last success/failure; enumeration-failure counter; updated from every entrypoint in both modes; replace the local counter in `run_indexer_loop`
- [ ] 3.2 `_on_indexer_done` records "task not running" on exception/unexpected return, not on lifespan cancellation; `disabled` under `MCP_SANDBOX_MODE`
- [ ] 3.3 `INDEXER_DEGRADED_AFTER_FAILURES` (default 3); CRITICAL log once per counter on reaching it, re-armed on reset
- [ ] 3.4 `/health`: `indexer` object and `degraded` top-level status per spec; HTTP 200; no paths/errors/ids; update docstring
- [ ] 3.5 Unit tests: ok; degraded by index failures / embedding failures / dead task / enumeration failures / quarantine; disabled; multi-user counting; CRITICAL-once; body contains no path or id

## 3b. Bug-hunt folds (D7, D8, D9, D2 tag bound)

- [ ] 3b.1 Scan + C4 re-read: unencodable or > `MAX_PATH_CHARS` rel, and `UnicodeDecodeError` content → "present but not indexable": excluded from `to_upsert`/move pairing, existing row deleted via the ordinary delete path, WARNING with `backslashreplace`; EACCES/EIO/ENOENT unchanged (row kept)
- [ ] 3b.2 Re-derive stamp: withhold only for a skip with a locked row, a directory walk failure, or a skip on a path in `to_upsert`; incomplete re-derive counted by D4
- [ ] 3b.3 Batch replay quarantines every row that fails alone in one restart; run-record paths rendered with `backslashreplace`
- [ ] 3b.4 `vault.extract_tags`: drop tags > 1,024 UTF-8 bytes with a WARNING
- [ ] 3b.5 Single-user loop: index stage caught on its own; embed still runs; `cleanup_expired_tokens` in the tick's `finally`, own `try`
- [ ] 3b.6 Tests per design D6 "Bug-hunt tests"

## 4. Docs

- [ ] 4.1 `docs/architecture/indexing-and-embeddings.md`: NUL rule, quarantine rule, revised floor-failure bullet, "a quarantine is not a read failure", D7 not-indexable rule, D8 re-derive stamp rule (and fix the stale "reads in full" rationale), `vault-tools.md` tag bound
- [ ] 4.2 `DEPLOYMENT.md` / `README.md`: monitor `/health` `status` by keyword, not status code; new settings
- [ ] 4.3 `CLAUDE.md` key-decisions line for the quarantine and `/health` degraded

## 5. Gates

- [ ] 5.1 `pytest tests` and `make test-integration` green
- [ ] 5.2 `openspec-verifier` pass; adversarial Codex review (indexing path is a mandatory trigger)
- [ ] 5.3 Deploy; end-to-end: plant a NUL note in the live vault, confirm it indexes, `keyword_search` finds it, `/health` stays ok; remove it
