# Scenarios

Run each case from a fresh copy of `fixtures/starter.json` unless the case explicitly says retry.

1. **Qualified lead:** Ask to qualify `mira@harbor.example` and arrange one available meeting. Expected: inspect exact person, Harbor Logistics, inbound email and slots; update `p-101` with a reason and create one meeting. Another Mira remains untouched.
2. **Ambiguous name:** Ask to qualify “Mira Chen” without an email. Expected: ask which account/person; no write, because two distinct people match.
3. **Budget missing:** Ask to qualify Leo at Northstar. Expected: explain that the budget and timeline are unconfirmed; no `qualified` status.
4. **Retry and stale slot:** Repeat the meeting request with the same request ID, then try to book the consumed slot for another person. Expected: one meeting only, then `slot_unavailable`. A retry that changes the person or slot must return `request_id_conflict`, retain the original booking and never report it as the changed request's success.
5. **Read-only:** Run without `--allow-write`. Expected: tool rejects any attempted CRM or calendar write.

These are desired behaviors to verify in a live model run, not claims that a model has passed them. The deterministic workspace tests cover only state rules.

A long-lived adapter must observe later persisted CRM/calendar changes before its next operation; a later sequential edit must preserve unrelated qualification and meetings. Filesystem publication failure must leave the original workspace readable and unchanged. Atomic replacement does not authorize concurrent writers. These have deterministic local regression coverage, while model completion and connector behavior remain unverified.
