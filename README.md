# Knight Insurance - Submission Review

## Known limitations and assumptions

- Packet shape: each submission packet is assumed to contain one broker email (pasted text, or an upload named `broker_email.txt`; pasted text wins if both are given), one application PDF named `application.pdf`, one vehicle schedule CSV, and zero or one loss runs PDF. The supplied materials do not specify file counts; extra files of the same type are not handled specially (only the first CSV is counted).
- Agent retries: an agent's final answer is schema-validated (including allowed fields and packet file names). A rejected answer goes back to the model as a tool error in the same run, up to 2 times. A third rejection marks that source `VALIDATION_FAILED`: its fields become `INVALID` with the error as evidence, while other sources, the CSV count and the rules are still saved and the reviewer can resolve the fields with overrides. A narrative that fails this way is marked failed and the deterministic results remain. Prompts are static; there is no prompt switching at runtime.
- Model failures: transport errors are retried twice per model. An optional fallback model (`LLM_FALLBACK_*` env vars) is tried after that; there is no further fallback. A source whose models all fail is shown as `MODEL_FAILED` and its fields as `INVALID`.
- Agent access: each agent only reads its own in-memory files (`/submission` or `/review`), which exist for one run only. It cannot write files, run commands or spawn subagents.
