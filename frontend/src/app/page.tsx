"use client";

import { Fragment, useRef, useState } from "react";
import { getSubmission, streamSubmission } from "@/lib/api";
import type { ProgressEvent, SubmissionDetail } from "@/lib/types";
import { ActivityPanel } from "@/components/activity-panel";
import { FieldReview } from "@/components/field-review";
import { HistoryPanel } from "@/components/history-panel";
import { NarrativePanel } from "@/components/narrative-panel";
import { ProgressFeed } from "@/components/progress-feed";
import { RuleResults } from "@/components/rule-results";
import { SubmissionForm } from "@/components/submission-form";

type Phase = "idle" | "processing" | "error" | "done";

const RUN_STYLES: Record<string, string> = {
  SUCCEEDED: "bg-emerald-100 text-emerald-800",
  SKIPPED: "bg-slate-100 text-slate-700",
  MODEL_FAILED: "bg-red-100 text-red-800",
  VALIDATION_FAILED: "bg-red-100 text-red-800",
};

function PacketSummary({ detail }: { detail: SubmissionDetail }) {
  const failed = detail.source_runs.filter(
    (run) => run.status === "MODEL_FAILED" || run.status === "VALIDATION_FAILED",
  );
  return (
    <section className="flex flex-col gap-3">
      {failed.length > 0 && (
        <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-900">
          <p className="font-semibold">
            Extraction did not complete for {failed.map((run) => run.source).join(", ")}.
          </p>
          <p>Affected fields are shown as missing or unknown; deterministic rules still ran on what was read.</p>
          <ul className="mt-1 list-disc pl-5">
            {failed.map((run) => (
              <li key={run.source}>
                {run.source}: {run.status}
                {run.error && ` — ${run.error}`}
              </li>
            ))}
          </ul>
        </div>
      )}
      <div className="card flex flex-col gap-3 text-sm md:flex-row md:justify-between">
        <div>
          <h2 className="mb-1 font-semibold">Documents</h2>
          <ul className="flex flex-wrap gap-2">
            {detail.documents.map((doc) => (
              <li
                key={doc.file_name}
                className={`badge ${doc.readable ? "bg-slate-100 text-slate-800" : "bg-amber-100 text-amber-900"}`}
              >
                {doc.file_name}
                {doc.detected_type && ` · ${doc.detected_type}`}
                {!doc.readable && " · unreadable"}
              </li>
            ))}
            {detail.documents.length === 0 && <li className="text-slate-500">None</li>}
          </ul>
        </div>
        <div>
          <h2 className="mb-1 font-semibold">Extraction runs</h2>
          <ul className="flex flex-wrap gap-2">
            {detail.source_runs.map((run) => (
              <li key={run.source} className={`badge ${RUN_STYLES[run.status]}`}>
                {run.source}: {run.status}
              </li>
            ))}
          </ul>
        </div>
      </div>
    </section>
  );
}

export default function Home() {
  const [detail, setDetail] = useState<SubmissionDetail | null>(null);
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<ProgressEvent[]>([]);
  const [refreshKey, setRefreshKey] = useState(0);
  const [historyOpen, setHistoryOpen] = useState(false);
  // Only the latest history click may apply, so a slow earlier load cannot replace it.
  const selection = useRef(0);

  async function submit(emailText: string, files: File[]) {
    // Drop all prior applicant data before the new packet starts.
    selection.current += 1;
    setDetail(null);
    setError(null);
    setEvents([]);
    setPhase("processing");
    try {
      setDetail(
        await streamSubmission(emailText, files, (event) =>
          setEvents((current) => [...current, event]),
        ),
      );
      setPhase("done");
      setRefreshKey((key) => key + 1);
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Submission failed.");
      setPhase("error");
    }
  }

  async function select(id: string) {
    if (phase === "processing") return; // a running review owns the page until it ends
    const ticket = ++selection.current;
    try {
      const loaded = await getSubmission(id);
      if (ticket !== selection.current) return;
      setEvents([]);
      setError(null);
      setDetail(loaded);
      setPhase("done");
      setHistoryOpen(false);
    } catch (caught) {
      if (ticket !== selection.current) return;
      setDetail(null);
      setError(caught instanceof Error ? caught.message : "Could not load submission.");
      setPhase("error");
    }
  }

  // Overrides and narrative edits can change the status shown in history.
  function update(next: SubmissionDetail) {
    setDetail(next);
    setRefreshKey((key) => key + 1);
  }

  function reset() {
    selection.current += 1;
    setDetail(null);
    setError(null);
    setEvents([]);
    setPhase("idle");
  }

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-slate-200 bg-white/80 backdrop-blur">
        <div className="mx-auto flex max-w-6xl items-center justify-between px-4 py-3">
          <div>
            <h1 className="text-lg font-semibold tracking-tight">Submission Review</h1>
            <p className="text-xs text-slate-500">Commercial auto · underwriter workspace</p>
          </div>
          <div className="flex gap-2">
            <button
              className="btn lg:hidden"
              aria-expanded={historyOpen}
              onClick={() => setHistoryOpen((open) => !open)}
            >
              History
            </button>
            {(detail || phase === "error") && (
              <button className="btn" onClick={reset}>
                New packet
              </button>
            )}
          </div>
        </div>
      </header>

      <div className="mx-auto grid max-w-7xl gap-6 px-4 py-6 lg:grid-cols-[18rem_minmax(0,1fr)]">
      <div className={historyOpen ? "block" : "hidden lg:block"}>
        <HistoryPanel selectedId={detail?.id ?? null} refreshKey={refreshKey} onSelect={select} />
      </div>
      <main className="flex min-w-0 flex-col gap-6">
        {!detail && <SubmissionForm busy={phase === "processing"} onSubmit={submit} />}

        {phase === "idle" && (
          <p className="text-center text-sm text-slate-500">Add a broker email and/or packet files to begin.</p>
        )}

        {phase === "processing" && <ProgressFeed events={events} />}

        <ActivityPanel events={events} running={phase === "processing"} />

        {phase === "error" && error && (
          <div className="rounded-2xl border border-red-200 bg-red-50 p-4 text-sm text-red-900" role="alert">
            <p className="font-semibold">Could not process this packet.</p>
            <p>{error}</p>
          </div>
        )}

        {detail && (
          <Fragment key={detail.id}>
            <RuleResults detail={detail} />
            <PacketSummary detail={detail} />
            <FieldReview detail={detail} onUpdate={update} />
            <NarrativePanel detail={detail} onUpdate={update} />
          </Fragment>
        )}
      </main>
      </div>
    </div>
  );
}
