# Knight Insurance - Submission Review

Helps an underwriter review a fictional commercial auto submission: upload a packet or paste a broker email, extract the eight business fields and the derived vehicle schedule count with evidence using an LLM, apply the deterministic rules R1-R5, then show an AI summary and an editable draft broker email. The email is never sent.

The brief and supplied materials are under `Knight_Insurance_24_Hour_Project/candidate_materials/` (`Assignment_Brief.pdf`, `field_specification.json`, `rules.json`, `sample_submissions/SUB-A`, `SUB-B`, `SUB-C`).

## Architecture

```
packet (pasted email and/or files)
  -> deterministic preparation: PDF text (pypdf), CSV schedule row count, file inventory
  -> three isolated extraction agents, run concurrently: the email agent reads only the broker
     email (pasted text or the email file), the PDF agent reads only `application.pdf`, and the
     attachments agent gets the other files (not the counted vehicle schedule) and reads only those that could be loss runs
       each sees only its own read-only in-memory files and must return a schema-validated
       answer with evidence (source file, locator, excerpt)
  -> deterministic normalization and reconciliation (MISSING / KNOWN / CONFLICT / INVALID)
  -> deterministic rules R1-R5 and overall status (no LLM)
  -> narrative agent: summary, draft email (display only)
  -> SQLite (WAL): packet, field states with evidence, rule snapshots, narrative
```

- `backend/`: FastAPI, `deepagents` (LangChain) agents, `sqlmodel` over SQLite, managed with `uv`.
- `frontend/`: Next.js (App Router, TypeScript, Tailwind).
- The LLM is used only for extraction and narrative text. Rule decisions are ordinary code in `backend/app/domain/rules.py`.
- Reviewer corrections are labelled overrides that keep the original value, state and evidence; rules rerun and a snapshot is stored.
- Each submission is processed independently; nothing carries over between packets.

HTTP API (all under `/submissions`): `POST /` (multipart `email_text` and `files`), `POST /stream` (same input, server-sent events), `GET /` (history list), `GET /{id}`, `PATCH /{id}/fields/{field}`, `PATCH /{id}/draft`, `POST /{id}/narrative/regenerate`, plus `GET /health`.

## Setup and run

Backend (from `backend/`, requires `uv` and Python 3.12 or newer):

```bash
uv sync
cp .env.example .env      # then set LLM_MODEL and LLM_API_KEY
uv run poe backend        # http://localhost:8000
```

Frontend (from `frontend/`, requires Node.js and npm):

```bash
npm install
npm run dev               # http://localhost:3000, API URL from NEXT_PUBLIC_API_URL
```

Run the two sides in separate terminals. The backend allows CORS only from `http://localhost:3000`; `NEXT_PUBLIC_API_URL` defaults to `http://localhost:8000`.

To try a sample, open http://localhost:3000, choose all files in one folder under `candidate_materials/sample_submissions/` (for example `SUB-A`), and submit. Pasting a broker email instead of uploading one also works.

## LLM configuration

Set in `backend/.env` (only `.env.example` is committed):

| Variable | Meaning |
|---|---|
| `LLM_MODEL` | `provider:model`, e.g. `anthropic:claude-sonnet-4-5` or `google_genai:gemini-2.5-flash` |
| `LLM_API_KEY` | key for that provider |
| `LLM_BASE_URL` | optional, for a compatible or local endpoint |
| `LLM_FALLBACK_MODEL`, `LLM_FALLBACK_API_KEY`, `LLM_FALLBACK_BASE_URL` | optional second model tried after the primary's retries fail |

Provider and model used: Anthropic, `claude-sonnet-5-5`, with `claude-haiku-5-5` as the fallback model.

Installed providers: `langchain-anthropic` and `langchain-google-genai`. Another provider needs its LangChain package added.

The API starts without a model. Each extraction source then shows `MODEL_FAILED` (its fields `INVALID`), the narrative shows `FAILED`, and the deterministic results (CSV count, rules) are still produced.

## Tests

From `backend/`:

```bash
uv run poe check    # ruff, then pytest
uv run poe test     # pytest only
```

Result: 251 passed. Tests use fake models and make no network calls. They cover missing information, source conflicts, unequal vehicle counts, the 150 vs 150.1 mile threshold, all three sample packets through the HTTP API, overrides, persistence across app instances, narrative failure and edits, and the input cases under Known limitations.

Frontend (from `frontend/`): `npm run lint`. There is no frontend test suite.

## Implemented features

- Empty start screen; one packet from pasted email text and/or uploaded files, with processing, success and failure states.
- PDF text, CSV schedule counting and attachment inventory.
- LLM extraction of the eight business fields plus the derived schedule count, each value with source file, locator and excerpt; MISSING lists the inspected sources, and a missing loss runs report shows the attachment inventory.
- Conflict detection between email and PDF with both values and evidence kept and no source preference.
- Rules R1-R5 and overall status as in `rules.json`, each shown with its status, reason and the values or evidence used; conflicts and invalid values give UNKNOWN before any threshold test.
- Labelled human overrides with the original value and evidence retained; rules rerun and a snapshot history is kept.
- AI underwriter summary and editable draft broker email (marked stale after an override when edited).
- Model failures shown as states, never replaced by simulated output.
- Submission text is treated as data, never as instructions.

## Extra work (beyond the required flow)

Not required by the brief; the required flow works without them.

- **Live agent events:** the UI submits to `POST /submissions/stream` and shows a stage checklist (read the packet, extract per source, evaluate rules, draft summary and email) plus an "Agent activity" panel with one tab per agent (email, PDF, attachments, narrative) showing what that agent does as it happens: the model's own text, every tool call with its arguments (for example `read_file` and the submitted answer), and every tool output. The panel stays on screen after the review finishes, until a new packet is submitted or a stored submission is selected; events are not stored, so reloading the page or opening a history entry does not show them. The stream emits `progress` events, then exactly one `result` (the full submission) or `error`. `POST /submissions` is unchanged.
- **History panel:** a side panel backed by `GET /submissions?q=&sort=&order=&limit=` lists stored submissions with search by id or business name (literal, case-insensitive) and sorting by newest, oldest, id, status or business name. Selecting a row reloads that submission; `limit` is 1-200 and invalid `sort`, `order` or `limit` values return 422.
- Progress events have `kind` (`stage_started`, `stage_finished`, `agent_message`, `tool_call`, `tool_result`), `stage`, `source`, `label`, `status`, `tool` and `detail` (model text, tool arguments or tool output, clipped to 8000 characters with `truncated` set). They contain packet text, since the agents read it, and are streamed only, not stored. A failed run's error text is the `detail` of its finishing event. If the client disconnects mid-stream the review still completes and is stored.

## AI coding tools used

GitHub Copilot agent mode in VS Code (Claude model) with the Superpowers planning, review and test-driven-development skills, used to plan, implement, review and test. All code was reviewed and run by the author.

Approximate time spent: 4-5 hours over the course of one day.

## Known limitations and assumptions

- Packet shape: each submission is assumed to contain one broker email (pasted text, or an upload named `broker_email.txt`), application PDF named `application.pdf`, at most one vehicle schedule CSV and optionally loss run PDFs. The supplied materials do not specify file counts. Pasted text together with `broker_email.txt` is rejected with a 400.
- File handling: type comes from the name (case-insensitive): `broker_email.txt` is the email, then `.pdf`, `.csv`, and anything else is read as UTF-8 text and treated as an attachment. Any other `.txt` or `.eml` file is therefore an attachment, not the email. File names must be unique within a packet (case-insensitive) and `manifest.txt` is reserved; both are rejected with a 400. Directory parts of upload names are dropped. There is no upload size limit.
- Which agent reads which file: the PDF agent reads only the file named `application.pdf` (case-insensitive). Every other attachment goes to the attachments agent, except the vehicle schedule CSV that the code counts (the one readable CSV with the schedule header); no agent reads that file. The attachments agent's manifest lists names and types; the agent decides from that which files could be loss runs and reads only those (enforced by the prompt, not by code). With nothing left for it, the agent is skipped. An application saved under another name is therefore not used for the business fields, which stay `MISSING` unless the email states them.
- Vehicle schedule: the CSV must have the header `vehicle_id,vin,year,make,model`; the count is the number of nonblank rows after it, and zero rows is a valid count of 0. A missing header, non-UTF-8 content, or more than one CSV makes `schedule_vehicle_count` `INVALID` with evidence (R2 then reports UNKNOWN). VINs are not decoded or validated.
- Loss runs (R5): no attachment besides the application and the vehicle schedule is recorded as a known "no loss runs" (FLAG). A readable file typed `loss_runs` by the attachment agent gives PASS, even if another attachment is unreadable. Without one, any unreadable attachment makes the field `INVALID` (UNKNOWN), because it may be the report. The agent's answer is schema-checked against the document types it reported for the files it read: Yes needs evidence from a `loss_runs` file, No is rejected when a file is `loss_runs` or `unclassifiable`, and an `unclassifiable` file means MISSING (UNKNOWN). When every attachment is readable and none it read is `loss_runs` or `unclassifiable`, MISSING is rejected and the agent must answer No. A loss run whose name and type give no hint that it is one may be skipped without being read. A promise in the email does not count.
- Unreadable files: an unreadable email or a source whose files are all unreadable (for example a scanned application PDF) makes that source's fields `INVALID`, so the rules report UNKNOWN rather than FLAG for "absent", and an unreadable source overrides a `KNOWN` value from another source. An unreadable attachment other than the application only affects loss runs (R5).
- MISSING means a source was read and the value was absent. A failed or unreadable source gives INVALID for its fields. "Inspected sources" lists only files actually supplied, so it is empty when, for example, no email was provided.
- Normalization: blank or `Not provided` (case-insensitive) is missing; dates must be `YYYY-MM-DD`; states as code or full name; booleans only `Yes`/`No`/`true`/`false`; counts as whole numbers (`3.0` allowed); miles as plain numbers. Anything else (`about 150`, `Nov 1, 2026`, `11/01/2026`, `150 miles`) is INVALID rather than guessed, and a reviewer override resolves it. Numbers above 10^15 are INVALID. `business_name` is compared ignoring case only (`Acme LLC.` vs `Acme LLC` is a CONFLICT); `operations_description` also ignores a trailing period, since the sample email ends the sentence and the application does not.
- `operations_description` is extracted and compared across sources but no rule uses it, as the field specification states.
- Overrides are typed values; dates must be `YYYY-MM-DD`. `null` clears a value. Booleans for numeric fields, negative, infinite or oversized numbers are rejected with a 422. Reviewer overrides are the only way to resolve a conflict.
- Narrative failures keep what was already shown (summary, draft) and record the failure; after a failed regenerate the earlier text may predate the latest overrides, so check the shown status.
- No OCR: a PDF without selectable text is unreadable, so the affected fields are UNKNOWN with the file listed.
- Local single-user use: no authentication, CORS fixed to `http://localhost:3000`, SQLite file under `backend/data/` (git-ignored), no deletion of stored submissions.
- `LLM_MODEL` is needed for extraction and narrative; without it those parts report failure (see LLM configuration).
- Excerpts are not machine-verified against the source text: nothing checks that an excerpt appears in the file or that `raw_value` appears in its excerpt.
- Agent retries: an agent's final answer is schema-validated (including allowed fields and packet file names). A rejected answer goes back to the model as a tool error in the same run, up to 2 times. A third rejection marks that source `VALIDATION_FAILED`: its fields become `INVALID` with the error as evidence, while other sources, the CSV count and the rules are still saved and the reviewer can resolve the fields with overrides. A model that ends without returning an answer is treated the same way. Prompts are static; there is no prompt switching at run time.
- Model failures: transport errors are retried twice per model. An optional fallback model (`LLM_FALLBACK_*` env vars) is tried after that; there is no further fallback. A source whose models all fail is shown as `MODEL_FAILED` and its fields as `INVALID`.
- Agent access: each agent only reads its own in-memory files (`/submission` or `/review`), which exist for one run only. It cannot write files, run commands or spawn subagents. Packet text is treated as data, not instructions.
