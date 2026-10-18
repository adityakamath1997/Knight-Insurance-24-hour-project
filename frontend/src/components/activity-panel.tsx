import { useEffect, useRef, useState } from "react";

import type { ProgressEvent } from "@/lib/types";

type AgentKey = "email" | "pdf" | "attachments" | "narrative" | "system";

const AGENTS: { key: AgentKey; title: string }[] = [
  { key: "email", title: "Email agent" },
  { key: "pdf", title: "PDF agent" },
  { key: "attachments", title: "Attachment agent" },
  { key: "narrative", title: "Narrative agent" },
  { key: "system", title: "System" },
];

const FAILED = new Set(["MODEL_FAILED", "VALIDATION_FAILED", "FAILED"]);

function agentOf(event: ProgressEvent): AgentKey {
  if (event.source) return event.source;
  return event.stage === "narrative" ? "narrative" : "system";
}

const KIND_STYLE: Record<string, string> = {
  stage_started: "text-slate-500",
  stage_finished: "text-slate-500",
  agent_message: "text-indigo-700",
  tool_call: "text-slate-800",
  tool_result: "text-slate-600",
};

const DETAIL_TITLE: Record<string, string> = {
  tool_call: "arguments",
  tool_result: "output",
};

function Dot({ events, running }: { events: ProgressEvent[]; running: boolean }) {
  const finished = [...events].reverse().find((event) => event.kind === "stage_finished");
  if (!finished && running) {
    return (
      <span className="h-2.5 w-2.5 animate-spin rounded-full border-2 border-indigo-200 border-t-indigo-600" />
    );
  }
  const failed = finished?.status && FAILED.has(finished.status);
  return (
    <span
      className={`h-2.5 w-2.5 rounded-full ${failed ? "bg-red-500" : finished ? "bg-emerald-500" : "bg-slate-300"}`}
    />
  );
}

function AgentLog({ events }: { events: ProgressEvent[] }) {
  const box = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const el = box.current;
    if (el) el.scrollTop = el.scrollHeight;
  }, [events.length]);

  return (
    <div ref={box} className="max-h-96 overflow-y-auto text-xs">
      <ol className="flex flex-col gap-1.5">
        {events.map((event, index) => (
          <li key={index} className={KIND_STYLE[event.kind]}>
            <div className="flex flex-wrap items-baseline gap-x-2">
              <span>{event.label}</span>
              {event.tool && <code className="text-slate-500">{event.tool}</code>}
              {event.status && event.status !== "ok" && (
                <span className="text-slate-500">[{event.status}]</span>
              )}
            </div>
            {event.detail && (
              <details className="ml-3" open={event.kind === "agent_message"}>
                <summary className="cursor-pointer text-slate-500">
                  {DETAIL_TITLE[event.kind] ?? "details"}
                  {event.truncated && " (truncated)"}
                </summary>
                <pre className="mt-1 max-h-60 overflow-auto whitespace-pre-wrap break-words rounded bg-slate-50 p-2 text-[11px] text-slate-700">
                  {event.detail}
                </pre>
              </details>
            )}
          </li>
        ))}
      </ol>
    </div>
  );
}

// Stays on screen after the review ends; events are split into one tab per agent.
export function ActivityPanel({
  events,
  running,
}: {
  events: ProgressEvent[];
  running: boolean;
}) {
  const [picked, setPicked] = useState<AgentKey | null>(null);
  const [open, setOpen] = useState(true);

  const tabs = AGENTS.map((agent) => ({
    ...agent,
    events: events.filter((event) => agentOf(event) === agent.key),
  })).filter((agent) => agent.events.length > 0);
  if (tabs.length === 0) return null;
  const active = tabs.find((tab) => tab.key === picked) ?? tabs[0];

  return (
    <section className="card" aria-label="Agent activity">
      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold">Agent activity</h2>
        <button className="btn" aria-expanded={open} onClick={() => setOpen((value) => !value)}>
          {open ? "Hide" : "Show"}
        </button>
      </div>
      {open && (
        <>
          <div className="mt-3 flex flex-wrap gap-1 border-b border-slate-200" role="tablist">
            {tabs.map((tab) => (
              <button
                key={tab.key}
                role="tab"
                aria-selected={tab.key === active.key}
                onClick={() => setPicked(tab.key)}
                className={`-mb-px flex items-center gap-1.5 border-b-2 px-3 py-1.5 text-xs font-medium ${
                  tab.key === active.key
                    ? "border-indigo-600 text-indigo-700"
                    : "border-transparent text-slate-500 hover:text-slate-800"
                }`}
              >
                <Dot events={tab.events} running={running} />
                {tab.title}
                <span className="text-slate-400">{tab.events.length}</span>
              </button>
            ))}
          </div>
          <div className="mt-3" role="tabpanel">
            <AgentLog key={active.key} events={active.events} />
          </div>
        </>
      )}
    </section>
  );
}
