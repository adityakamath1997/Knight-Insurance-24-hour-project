"use client";

import { useState } from "react";
import { regenerateNarrative, saveDraft, sendMessage } from "@/lib/api";
import type { SubmissionDetail } from "@/lib/types";

export function NarrativePanel({
  detail,
  onUpdate,
}: {
  detail: SubmissionDetail;
  onUpdate: (detail: SubmissionDetail) => void;
}) {
  const { narrative } = detail;
  const [draft, setDraft] = useState(narrative.draft.body);
  const [syncedBody, setSyncedBody] = useState(narrative.draft.body);
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState<"save" | "regenerate" | "message" | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const unsaved = draft !== narrative.draft.body;

  // Adopt a server-side draft change (regenerate) without clobbering in-progress edits.
  if (narrative.draft.body !== syncedBody) {
    setSyncedBody(narrative.draft.body);
    setDraft(narrative.draft.body);
  }

  async function run(kind: "save" | "regenerate" | "message", action: () => Promise<SubmissionDetail>) {
    setError(null);
    setSaved(false);
    setBusy(kind);
    try {
      onUpdate(await action());
      if (kind === "save") setSaved(true);
      if (kind === "message") setMessage("");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Request failed.");
    } finally {
      setBusy(null);
    }
  }

  return (
    <section className="flex flex-col gap-4">
      <h2 className="text-xl font-semibold tracking-tight">Summary and draft email</h2>

      {narrative.status === "FAILED" && (
        <p className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-900" role="alert">
          The narrative model call failed: {narrative.error ?? "unknown error"}. Rule results above are
          unaffected.
        </p>
      )}
      {narrative.status === "NOT_RUN" && (
        <p className="card text-sm text-slate-600">No summary has been generated.</p>
      )}

      {narrative.summary && (
        <div className="card">
          <h3 className="mb-1 text-sm font-semibold uppercase tracking-wide text-slate-500">Summary</h3>
          <p className="whitespace-pre-wrap text-sm leading-relaxed">{narrative.summary}</p>
        </div>
      )}

      {narrative.draft.stale && (
        <p className="rounded-2xl border border-amber-200 bg-amber-50 p-4 text-sm text-amber-900">
          A correction was made after this draft was written, so it may be out of date. Use Regenerate to
          rewrite it (this replaces your edits).
        </p>
      )}

      <div className="card flex flex-col gap-2">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <label className="font-medium" htmlFor="draft">
            Draft email to broker
          </label>
          <span className="text-xs text-slate-500">Display only — never sent</span>
        </div>
        <textarea
          id="draft"
          className="input min-h-56 leading-relaxed"
          value={draft}
          onChange={(event) => {
            setDraft(event.target.value);
            setSaved(false);
          }}
        />
        <div className="flex flex-wrap items-center gap-2">
          <button
            className="btn-primary"
            disabled={busy !== null || !unsaved}
            onClick={() => run("save", () => saveDraft(detail.id, draft))}
          >
            {busy === "save" ? "Saving…" : "Save draft"}
          </button>
          <button
            className="btn"
            disabled={busy !== null}
            onClick={() => run("regenerate", () => regenerateNarrative(detail.id))}
          >
            {busy === "regenerate" ? "Regenerating…" : "Regenerate"}
          </button>
          {unsaved && <span className="text-xs text-amber-700">Unsaved changes</span>}
          {saved && !unsaved && <span className="text-xs text-emerald-700">Saved</span>}
          {narrative.draft.edited && !unsaved && !saved && (
            <span className="text-xs text-slate-500">Edited by reviewer</span>
          )}
        </div>
      </div>

      <div className="card flex flex-col gap-3">
        <h3 className="font-medium">Ask about this submission</h3>
        {narrative.messages.length > 0 && (
          <ul className="flex flex-col gap-2">
            {narrative.messages.map((item, index) => (
              <li
                key={index}
                className={`rounded-xl p-3 text-sm ${
                  item.role === "reviewer" ? "ml-8 bg-indigo-50" : "mr-8 bg-slate-100"
                }`}
              >
                <div className="mb-0.5 text-xs font-semibold uppercase text-slate-500">{item.role}</div>
                <div className="whitespace-pre-wrap">{item.content}</div>
              </li>
            ))}
          </ul>
        )}
        <form
          className="flex gap-2"
          onSubmit={(event) => {
            event.preventDefault();
            if (message.trim()) run("message", () => sendMessage(detail.id, message));
          }}
        >
          <input
            className="input"
            value={message}
            onChange={(event) => setMessage(event.target.value)}
            placeholder="Ask a question…"
          />
          <button className="btn-primary" disabled={busy !== null || !message.trim()}>
            {busy === "message" ? "Sending…" : "Ask"}
          </button>
        </form>
      </div>

      {error && <p className="text-sm text-red-700">{error}</p>}
    </section>
  );
}
