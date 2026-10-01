## MODIFIED Requirements

### Requirement: `/health` SHALL report indexer degradation without disclosing paths or tenants

The `/health` response SHALL include an `indexer` object carrying `status` (`ok`, `degraded` or `disabled`), `task_running`, `failing_scopes` (scopes whose index failure count is at or above `INDEXER_DEGRADED_AFTER_FAILURES`), `embedding_failing_scopes` (likewise for embedding failures, counted as in the index-integrity failure-accounting requirement), `max_consecutive_failures`, `quarantined_notes` (quarantined notes across all scopes) and `last_success_at` (the most recent successful index pass of any scope, or null). `indexer.status` and the top-level `status` SHALL be `degraded` when the indexer task is recorded as not running, when any index, embedding, incomplete-re-derive, incomplete-walk or enumeration failure counter is at or above the threshold, or when `quarantined_notes` is greater than zero; `indexer.status` SHALL be `disabled` when indexing is intentionally not run (`MCP_SANDBOX_MODE`), which SHALL NOT by itself make the top-level status `degraded`. The HTTP status code SHALL remain 200 in every case, so liveness and readiness probes are unaffected. The response SHALL be computed from in-process state only, without probing, and SHALL NOT contain any path, error message, SQLSTATE or user identifier.

#### Scenario: A healthy indexer reports ok

- **WHEN** the indexer task is running, no counter is at the threshold and nothing is quarantined
- **THEN** `/health` SHALL return 200 with `status` `ok` and `indexer.status` `ok`

#### Scenario: A repeatedly failing indexer reports degraded

- **WHEN** a scope's index pass has failed `INDEXER_DEGRADED_AFTER_FAILURES` times in a row
- **THEN** `/health` SHALL return 200 with `status` `degraded`, `indexer.failing_scopes` at least 1 and `indexer.max_consecutive_failures` at least that count

#### Scenario: An embedding outage reports degraded

- **WHEN** a scope's embed passes have reported per-note embedding failures (or the embed stage raised) `INDEXER_DEGRADED_AFTER_FAILURES` times in a row
- **THEN** `/health` SHALL report `status` `degraded` and `indexer.embedding_failing_scopes` at least 1

#### Scenario: A dead indexer task reports degraded

- **WHEN** the indexer background task has ended by exception while the application keeps serving
- **THEN** `/health` SHALL return 200 with `status` `degraded` and `indexer.task_running` false

#### Scenario: A quarantined note reports degraded without naming it

- **WHEN** one note is quarantined
- **THEN** `/health` SHALL report `status` `degraded` and `indexer.quarantined_notes` 1
- **AND** the response body SHALL NOT contain the note's path or its owner's identifier

## ADDED Requirements

### Requirement: An administrator SHALL be able to confirm that a vault was emptied on purpose

The control panel SHALL offer administrators a "Confirm vault is empty" action — in the settings Danger zone in single-user mode, and on each user's edit page in multi-user mode — that grants that scope the single-use, 15-minute empty-prune permission defined by index-integrity and starts a background index pass for that scope. The action SHALL require a signed, single-use confirmation token issued by a confirmation page that states how many indexed notes will be deleted if the vault is empty; a missing, forged, reused or expired token SHALL be refused with nothing granted. The control SHALL follow the panel's content-security rules: no inline handlers or style attributes, a `type="button"` confirm control that fails closed. Granting SHALL be logged at WARNING with the administrator's username and the scope. Non-administrators SHALL NOT see or reach the action.

#### Scenario: An administrator confirms an emptied vault

- **WHEN** an administrator opens the confirmation page for a scope whose index holds 50 notes and confirms with a valid token
- **THEN** the page SHALL have stated that 50 notes will be deleted, the scope SHALL hold an empty-prune permission, and a background pass for that scope SHALL have been started

#### Scenario: A replayed or forged confirmation grants nothing

- **WHEN** the confirm request carries a token that was already used, has expired, or was not issued by the server
- **THEN** no permission SHALL be granted and no pass SHALL be started

#### Scenario: A non-administrator cannot confirm

- **WHEN** a non-administrator requests the confirmation page or posts the confirm action
- **THEN** the request SHALL be refused
