## MODIFIED Requirements

### Requirement: Keyword indexing attempts full content and degrades per-note without aborting the pass

The tsvector build (incremental pass and full rebuild alike) SHALL attempt the note's full content. Each attempt SHALL run inside its own savepoint, entered such that a database error unwinds the savepoint through the context manager's rollback before any retry (the failure handling sits outside the savepoint context, so the outer transaction is never left in the aborted state). On failure the build SHALL retreat by halving the content, one fresh savepoint per attempt, down to a floor of exactly 100,000 characters — the pre-change statement. A failure at the floor SHALL propagate out of the build, and the two call sites SHALL provide different — but individually stated — guarantees: in the **incremental pass** a floor failure whose SQLSTATE marks it a poison failure SHALL quarantine that note and the pass SHALL be re-run without it, committing every other note (see "A note that fails at a per-note database boundary is quarantined, not fatal to its owner's pass"), while any other floor failure aborts the pass with nothing committed; the **full rebuild** SHALL be atomic — no intermediate commits — so a floor failure rolls the entire rebuild back and the error surfaces to the operator who invoked it, never leaving a keyword index half-built under two FTS configurations that no periodic pass would repair.

Verification of the savepoint behavior SHALL include a real-PostgreSQL integration test (mocks cannot prove the driver's aborted-transaction state clears): induce a genuine statement failure, observe the bounded retry succeed within the same outer transaction, perform a further update, commit, and verify both rows.

**The full rebuild SHALL update only rows it certifies.** It snapshots the table once and then reads the vault note by note, so both the rows and the files move underneath it — and a keyword vector is only ever rewritten again when a note's `content_hash` changes, because both move paths preserve `content_tsvector` and the ordinary scan skips a row whose hash is unchanged. A row the rebuild steps over, or writes the wrong bytes into, therefore stays on the previous configuration with nothing that would ever revisit it.

The rebuild's snapshot SHALL therefore retain each row's owner, relative path and content hash; the bytes it reads SHALL be verified to hash to that retained content hash before anything is written; and its UPDATE SHALL be conditional on all four of id, owner, relative path and content hash, and SHALL require that exactly one row matched. A zero-row update, a read failure, or a hash mismatch SHALL NOT be committed around and SHALL NOT be routed through the size-halving retreat, which addresses a size failure and cannot fix a stale target. Each SHALL instead trigger a bounded re-read of the current owner-scoped row: a row that is gone is safely absent and SHALL be skipped; a row whose path or hash has changed SHALL be retried against those fresh values within a bounded number of attempts; and a row that still records the path and hash the rebuild acted on — an unreadable file, or bytes the scan has not caught up with — SHALL abort the whole rebuild, which being one transaction rolls every other note back with it.

#### Scenario: A note moved mid-rebuild is repaired, never stepped over

- **WHEN** a note's `file_path` changes (by either move path) after the rebuild's snapshot and before it reads that row, so the read at the snapshotted path fails
- **THEN** the rebuild SHALL re-read the row, retry against its current path, and write that row's tsvector under the current configuration
- **AND** it SHALL NOT commit the remaining notes while leaving that row on the previous configuration

#### Scenario: A stale write does not land when the content hash advances

- **WHEN** a concurrent index pass commits a new `content_hash` and a matching `content_tsvector` for a row between the rebuild's read of the earlier content and its UPDATE
- **THEN** the certified UPDATE SHALL match no row and the earlier content's tsvector SHALL NOT be written
- **AND** the rebuild SHALL re-read the row and rebuild it against the committed content, so the stored hash and the stored tsvector describe the same content

#### Scenario: A row it cannot certify aborts the whole rebuild

- **WHEN** the rebuild cannot read a note, or the bytes it reads do not hash to the row's `content_hash`, and a re-read shows the row still records that path and that hash
- **THEN** the rebuild SHALL abort and its transaction SHALL roll back, leaving every note's `content_tsvector` unchanged
- **AND** the error SHALL surface to the operator who invoked it, rather than the rebuild committing around that row

#### Scenario: A row deleted mid-rebuild is safely absent

- **WHEN** the row is deleted (or leaves the rebuild's owner scope) between the snapshot and the write
- **THEN** the rebuild SHALL skip it without aborting, because no row remains in scope to leave on the previous configuration

#### Scenario: Terms beyond the former 100K slice are searchable when the full build succeeds

- **WHEN** a valid note carries a distinctive term past 100,000 characters and its full-content tsvector build succeeds
- **THEN** after the next index of that note, `keyword_search` for that term SHALL return the note

#### Scenario: A pathological note degrades alone, and the degradation is bounded and logged

- **WHEN** a note's full-content tsvector exceeds PostgreSQL's size limit
- **THEN** the pass SHALL retreat to a bounded prefix for that note only, log the retreat with the prefix length, index the remaining notes normally, and commit
- **AND** terms present only beyond the successful prefix are accepted as unsearchable for that note — the declared degradation

#### Scenario: A poison floor failure in the incremental pass costs only that note

- **WHEN** even the 100,000-character floor attempt fails for a note during an incremental index pass with a data-exception (class 22) or program-limit (54000) SQLSTATE
- **THEN** that note SHALL be quarantined and its existing row SHALL remain exactly as before the pass, so its metadata hash does not advance
- **AND** the pass SHALL be re-run without that note and every other note in the scope SHALL be committed

#### Scenario: A non-poison floor failure still aborts the incremental pass

- **WHEN** the floor attempt fails for a reason outside the poison SQLSTATE set (for example a connection loss or lock timeout)
- **THEN** the error SHALL propagate and the pass SHALL abort with nothing committed, and the failure SHALL count toward the scope's consecutive failures

#### Scenario: A floor failure during a full rebuild rolls the whole rebuild back

- **WHEN** `rebuild_tsvectors` is processing a vault of more than 500 notes and a note's floor attempt fails after what would previously have been an intermediate commit boundary
- **THEN** the entire rebuild SHALL roll back — no note's tsvector changes — and the error SHALL surface to the invoking operator
- **AND** the keyword index SHALL never be left half-built under two FTS configurations

## ADDED Requirements

### Requirement: The indexer SHALL derive every indexed value from NUL-free text and SHALL NOT modify the note file

The indexer SHALL remove every U+0000 character from a note's text at the single point where the file's bytes are decoded, before the content hash is computed, so that the content hash, the keyword vector, the title, tags, links, chunk text and every re-verification by the embed, reconciliation, link-backfill and rebuild passes are derived from the same NUL-free text. A note containing no NUL SHALL produce exactly the text and content hash it produced before this change. The indexer SHALL additionally remove U+0000 from every string key and value written to the `frontmatter` JSONB column and from the derived title and tags, because a YAML escape can produce a NUL from NUL-free bytes. The note's bytes on disk SHALL NOT be modified, and the parsed frontmatter mapping used by `set_frontmatter` SHALL NOT be altered. Each read that removes a NUL SHALL log one WARNING naming the vault-relative path and the number removed, and SHALL NOT log note content.

#### Scenario: A note with a NUL in its body indexes (#308 repro)

- **WHEN** a note containing `hello\x00world\n` is discovered by an index pass
- **THEN** the pass SHALL complete and commit, the note's row SHALL be stored with the content hash of `helloworld\n`, and `keyword_search` for `helloworld` SHALL return the note
- **AND** the file SHALL still contain the NUL byte

#### Scenario: A NUL-bearing note embeds

- **WHEN** the embed pass processes a note whose file contains NUL bytes
- **THEN** its chunks SHALL be stored without NUL and the note SHALL be certified, without a stale-certification mismatch against the hash the scan committed

#### Scenario: A YAML-escaped NUL in frontmatter indexes

- **WHEN** a note's frontmatter contains `title: "a\0b"` and `tags: ["x\0y"]` and a key `"k\0": 1`
- **THEN** the pass SHALL complete, the stored title SHALL be `ab`, the stored tags SHALL include `xy`, and the stored JSONB SHALL carry the key `k`

#### Scenario: NUL-free notes keep their hashes across the deploy

- **WHEN** the first index pass after deploying this change runs over a vault whose notes contain no NUL
- **THEN** no note's `content_hash` SHALL change and no note SHALL be re-upserted on account of this change

### Requirement: A note that fails at a per-note database boundary SHALL be quarantined, not fatal to its owner's pass

A **poison failure** SHALL be a database error whose SQLSTATE is in class 22 (data exception) or is 54000 (program limit exceeded), raised while writing one identifiable note's derived data during an incremental index pass: either the keyword-vector build failing at its floor, or that note's row failing the batch upsert. When a batch upsert raises such an error, the pass SHALL replay that batch one row at a time, each in its own savepoint, to identify the failing row; if no single row fails alone, the error SHALL NOT be treated as a poison failure.

On a poison failure the pass's transaction SHALL roll back, the note SHALL be recorded in an in-process quarantine keyed by owner and vault-relative path together with the content hash that failed, and the pass SHALL be re-run for the same scope, at most `INDEXER_QUARANTINE_RETRIES_PER_TICK` times per scope per tick; beyond that bound the pass SHALL fail as an ordinary failure. While a note's current content hash equals its quarantined hash, every pass SHALL exclude it from upsert and SHALL leave its existing row, keyword vector, links and embeddings exactly as they were, so that no committed content hash is ever paired with derived data from other content. A quarantine SHALL NOT count as a read failure: it SHALL NOT keep the scope due for a full-hash pass and SHALL NOT make a re-derive incomplete. The entry SHALL be cleared when the note next indexes successfully, is deleted, or its scope's index is discarded. Quarantining SHALL log one ERROR naming the path and SQLSTATE and no content, and the pass's run record SHALL name the quarantined paths (at most five, then an ellipsis) in its error field. The full keyword rebuild is excluded from this requirement and SHALL remain atomic.

#### Scenario: One poison note does not stop its owner's index

- **WHEN** a scope contains 50 changed notes and one of them raises a poison failure on its keyword-vector write
- **THEN** the other 49 notes SHALL be committed with new hashes and keyword vectors in the same tick
- **AND** the poison note's row SHALL be unchanged and the pass SHALL NOT be retried for it on the next tick while its content is unchanged

#### Scenario: A poison row in the batch upsert is identified and quarantined

- **WHEN** one row of a 100-row upsert batch raises a class-22 error
- **THEN** the pass SHALL identify that row by per-row replay, quarantine it, and commit the other 99

#### Scenario: Editing a quarantined note retries it

- **WHEN** a quarantined note's content is edited so that it no longer fails
- **THEN** the next index pass SHALL index it and clear its quarantine entry

#### Scenario: A quarantine does not re-arm a whole-scope rewrite

- **WHEN** a quarantined note is present during a re-derive or a full-hash pass
- **THEN** that pass SHALL commit, SHALL record its completion, and the following tick SHALL NOT re-upsert the scope's unchanged notes

#### Scenario: The retry bound is honoured

- **WHEN** more poison failures occur in one scope in one tick than `INDEXER_QUARANTINE_RETRIES_PER_TICK`
- **THEN** the pass SHALL fail with nothing committed for that attempt and the failure SHALL count toward the scope's consecutive failures, while the notes already quarantined stay quarantined for the next tick

### Requirement: Consecutive index-pass failures SHALL be counted per scope in single-user and multi-user modes

The indexer SHALL keep, per scope, the number of consecutive failed index passes, the time of the last successful pass and the time of the last failure, updated by the same code path in single-user and multi-user modes. A successful pass SHALL reset the scope's count to zero. The CRITICAL "manual intervention required" log SHALL be emitted once when a scope's count first reaches `INDEXER_DEGRADED_AFTER_FAILURES` (default 3), and not again until the count has been reset.

#### Scenario: A failing tenant is counted in multi-user mode

- **WHEN** in multi-user mode one user's index pass fails on three consecutive ticks while other users' passes succeed
- **THEN** that user's scope SHALL have a consecutive-failure count of 3 and the CRITICAL log SHALL have been emitted exactly once
