## 1. Walk and prune protection (D1, D2)

- [ ] 1.1 `discover_markdown_files_at`: record the vault-relative prefix (`""` for the root) for every directory failure already recorded as a skip; `ScanResult.walk_failed_prefixes`
- [ ] 1.2 `_index_vault_attempt`: compute protected paths from `locked` (`p == pref` or `p.startswith(pref + "/")`, `pref != ""`); remove them from the prune set before `deleted_by_hash`; skip their quarantine-clear
- [ ] 1.3 WARNING naming unlisted dirs (bounded) and rows protected; run-record line `walk incomplete: N dir(s) not listed: …` (≤ 5, backslashreplace); `run_outcome` labels it failed; `IndexPassResult` exposes the count

## 2. Indeterminate root (D3, D5 consumption)

- [ ] 2.1 `IndexIndeterminate`; raise in `_index_vault_pinned` before the lock on root listing failure, or on empty `seen` with snapshot rows and no unexpired permission
- [ ] 2.2 Re-evaluate against `locked` in `_index_vault_attempt` before any mutation
- [ ] 2.3 Empty-prune permission registry (in-process, per scope, 15-min TTL, single-use, consumed by the first pass that evaluates the predicate); WARNING on consume with rows pruned
- [ ] 2.4 Error text per spec (condition + row count + where to confirm; no path)

## 3. Accounting (D4)

- [ ] 3.1 `indexer_health`: `walk_incomplete` per scope, wired from `IndexPassResult` at every entrypoint; counts toward degraded, `max_consecutive_failures`, CRITICAL once per episode

## 4. Panel (D5)

- [ ] 4.1 Admin-only confirmation page (signed single-use token, states the row count) + POST action that grants the permission and starts `_reindex_background` for that scope; WARNING with admin username and scope
- [ ] 4.2 Single-user: settings Danger zone control; multi-user: user edit page control; CSP rules (`data-*`, nonce, `type="button"` + `data-confirm`, no inline style)

## 5. Tests (D6)

- [ ] 5.1 Unit tests per design D6
- [ ] 5.2 Real-Postgres tests per design D6

## 6. Docs

- [ ] 6.1 `docs/architecture/indexing-and-embeddings.md` (prefix protection, indeterminate root, permission), `docs/architecture/control-panel.md` (the new action), `DEPLOYMENT.md` pitfall + L1, `docs/deployment-kubernetes.md` troubleshooting row, `CLAUDE.md` key-decisions bullet

## 7. Gates

- [ ] 7.1 Offline suite and `make test-integration` green
- [ ] 7.2 `openspec-verifier`; adversarial Codex (deletion path → mandatory)
- [ ] 7.3 Deploy (k3s image bump PR); live check; owner browser/CSP pass on the new panel controls
