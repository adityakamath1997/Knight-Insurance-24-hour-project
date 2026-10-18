"use client";

import { Fragment, useState } from "react";
import { createSubmission } from "@/lib/api";
import type { SubmissionDetail } from "@/lib/types";
import { FieldReview } from "@/components/field-review";
import { NarrativePanel } from "@/components/narrative-panel";
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

  async function submit(emailText: string, files: File[]) {
    // Drop all prior applicant data before the new packet starts.
    setDetail(null);
    setError(null);
    setPhase("processing");
    try {
      setDetail(await createSubmission(emailText, files));
      setPhase("done");
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Submission failed.");
      setPhase("error");
    }
  }

  function reset() {
    setDetail(null);
    setError(null);
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
          {detail && (
            <button className="btn" onClick={reset}>
              New packet
            </button>
          )}
        </div>
      </header>

      <main className="mx-auto flex max-w-6xl flex-col gap-6 px-4 py-6">
        {!detail && <SubmissionForm busy={phase === "processing"} onSubmit={submit} />}

        {phase === "idle" && (
          <p className="text-center text-sm text-slate-500">Add a broker email and/or packet files to begin.</p>
        )}

        {phase === "processing" && (
          <div className="card flex items-center gap-3" role="status">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600" />
            <span className="text-sm">Reading the packet and extracting fields. This can take a minute.</span>
          </div>
        )}

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
            <FieldReview detail={detail} onUpdate={setDetail} />
            <NarrativePanel detail={detail} onUpdate={setDetail} />
          </Fragment>
        )}
      </main>
    </div>
  );
}
