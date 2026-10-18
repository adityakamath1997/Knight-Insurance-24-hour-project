import type { ProgressEvent, ProgressStage, SourceName } from "@/lib/types";

const STAGES: { stage: ProgressStage; title: string }[] = [
  { stage: "prepare", title: "Read the packet" },
  { stage: "extraction", title: "Extract fields with evidence" },
  { stage: "rules", title: "Evaluate rules R1-R5" },
  { stage: "narrative", title: "Draft summary and email" },
];

const SOURCES: { source: SourceName; title: string }[] = [
  { source: "email", title: "Email" },
  { source: "pdf", title: "PDF" },
  { source: "attachments", title: "Attachments" },
];

const FAILED = new Set(["MODEL_FAILED", "VALIDATION_FAILED", "FAILED"]);

type State = "pending" | "running" | "done" | "failed" | "skipped";

function stateOf(events: ProgressEvent[]): State {
  if (events.length === 0) return "pending";
  const finished = [...events].reverse().find((event) => event.kind === "stage_finished");
  if (!finished) return "running";
  if (finished.status && FAILED.has(finished.status)) return "failed";
  if (finished.status === "SKIPPED") return "skipped";
  return "done";
}

function Mark({ state }: { state: State }) {
  if (state === "running")
    return (
      <span className="h-4 w-4 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600" />
    );
  const style = {
    pending: "border border-slate-300 text-transparent",
    done: "bg-emerald-500 text-white",
    failed: "bg-red-500 text-white",
    skipped: "bg-slate-300 text-white",
  }[state];
  const glyph = { pending: "", done: "✓", failed: "!", skipped: "–" }[state];
  return (
    <span
      className={`flex h-4 w-4 items-center justify-center rounded-full text-[10px] font-bold leading-none ${style}`}
    >
      {glyph}
    </span>
  );
}

function latestToolLabel(events: ProgressEvent[]): string | null {
  const last = [...events].reverse().find((event) => event.kind.startsWith("tool_"));
  return last ? last.label : null;
}

export function ProgressFeed({ events }: { events: ProgressEvent[] }) {
  return (
    <div className="card" role="status" aria-live="polite">
      <h2 className="mb-3 text-sm font-semibold">Reviewing this packet</h2>
      <ol className="flex flex-col gap-2 text-sm">
        {STAGES.map(({ stage, title }) => {
          const stageEvents = events.filter((event) => event.stage === stage);
          const state =
            stage === "extraction" ? extractionState(stageEvents) : stateOf(stageEvents);
          return (
            <li key={stage}>
              <div className="flex items-center gap-2">
                <Mark state={state} />
                <span className={state === "pending" ? "text-slate-400" : ""}>{title}</span>
              </div>
              {stage === "extraction" && stageEvents.length > 0 && (
                <ul className="ml-6 mt-1.5 flex flex-col gap-1 text-xs text-slate-600">
                  {SOURCES.map(({ source, title: sourceTitle }) => {
                    const sourceEvents = stageEvents.filter((event) => event.source === source);
                    if (sourceEvents.length === 0) return null;
                    const sourceState = stateOf(sourceEvents);
                    const tool = latestToolLabel(sourceEvents);
                    return (
                      <li key={source} className="flex items-center gap-2">
                        <Mark state={sourceState} />
                        <span className="font-medium">{sourceTitle}</span>
                        <span className="truncate text-slate-500">
                          {sourceState === "running" && tool
                            ? tool
                            : sourceEvents[sourceEvents.length - 1].label}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              )}
            </li>
          );
        })}
      </ol>
    </div>
  );
}

// The stage is done once every source that started has finished; any failed run marks it failed.
function extractionState(events: ProgressEvent[]): State {
  if (events.length === 0) return "pending";
  const bySource = SOURCES.map(({ source }) => events.filter((event) => event.source === source));
  const started = bySource.filter((group) => group.length > 0);
  const states = started.map(stateOf);
  if (states.includes("running")) return "running";
  if (started.length < SOURCES.length) return "running";
  if (states.includes("failed")) return "failed";
  return "done";
}
