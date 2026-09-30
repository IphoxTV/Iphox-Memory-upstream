## ADDED Requirements

### Requirement: `/health` SHALL report indexer degradation without disclosing paths or tenants

The `/health` response SHALL include an `indexer` object carrying `status` (`ok` or `degraded`), `failing_scopes` (the number of scopes whose consecutive-failure count is at or above `INDEXER_DEGRADED_AFTER_FAILURES`), `max_consecutive_failures`, `quarantined_notes` (the number of quarantined notes across all scopes) and `last_success_at` (the most recent successful pass of any scope, or null). The top-level `status` SHALL be `degraded` when `failing_scopes` or `quarantined_notes` is greater than zero, and `ok` otherwise. The HTTP status code SHALL remain 200 in both cases. The response SHALL be computed from in-process state only, without probing, and SHALL NOT contain any path, error message, SQLSTATE or user identifier.

#### Scenario: A healthy indexer reports ok

- **WHEN** no scope has failed and nothing is quarantined
- **THEN** `/health` SHALL return 200 with `status` `ok` and `indexer.status` `ok`

#### Scenario: A repeatedly failing indexer reports degraded

- **WHEN** a scope's index pass has failed `INDEXER_DEGRADED_AFTER_FAILURES` times in a row
- **THEN** `/health` SHALL return 200 with `status` `degraded`, `indexer.failing_scopes` at least 1 and `indexer.max_consecutive_failures` equal to that count

#### Scenario: A quarantined note reports degraded without naming it

- **WHEN** one note is quarantined
- **THEN** `/health` SHALL report `status` `degraded` and `indexer.quarantined_notes` 1
- **AND** the response body SHALL NOT contain the note's path or its owner's identifier
