# Iphox Memory vault conventions

The runtime vault is data, not source code. Do not commit a real personal vault to this repository.

Recommended structure:

```text
/profile/
/projects/<PROJECT>/
/decisions/
/preferences/
/rules/
/lessons/
/handoffs/
/sessions/
/archive/
```

Rules:

- Notes use stable `memory_id` values independent of filenames.
- Project names are canonical identifiers (`FIBER`, `NULL-SELF`, etc.), not free-form aliases.
- New information does not silently overwrite conflicting active truth. It creates a candidate,
  then either updates the same note with provenance or supersedes the old note explicitly.
- `handoff` notes are concise continuation state, not chat transcripts.
- Secrets, passwords, API keys, recovery codes, private tokens and authentication challenges are forbidden.
- Derived embeddings, database rows and graph indexes are never canonical memory.
