import type { RuleStatus, SubmissionDetail } from "@/lib/types";

const STATUS_STYLES: Record<RuleStatus, string> = {
  PASS: "bg-emerald-100 text-emerald-800",
  FLAG: "bg-red-100 text-red-800",
  UNKNOWN: "bg-amber-100 text-amber-800",
};

const BORDER_STYLES: Record<RuleStatus, string> = {
  PASS: "border-l-emerald-500",
  FLAG: "border-l-red-500",
  UNKNOWN: "border-l-amber-500",
};

function show(value: string | number | boolean | null) {
  if (value === null) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

export function RuleResults({ detail }: { detail: SubmissionDetail }) {
  const ready = detail.overall_status === "READY_FOR_REVIEW";
  return (
    <section className="flex flex-col gap-3">
      <div
        className={`rounded-2xl border p-4 ${
          ready ? "border-emerald-200 bg-emerald-50 text-emerald-900" : "border-amber-200 bg-amber-50 text-amber-900"
        }`}
      >
        <div className="text-lg font-semibold">{ready ? "Ready for human review" : "Needs review"}</div>
        <div className="text-sm opacity-80">Readiness for human review only, not a coverage decision.</div>
      </div>
      <ul className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {detail.rules.map((rule) => (
          <li key={rule.id} className={`card border-l-4 ${BORDER_STYLES[rule.status]}`}>
            <div className="flex items-start justify-between gap-2">
              <h3 className="font-medium">
                <span className="text-slate-400">{rule.id}</span> {rule.name}
              </h3>
              <span className={`badge ${STATUS_STYLES[rule.status]}`}>{rule.status}</span>
            </div>
            <p className="mt-1 text-sm text-slate-700">{rule.reason}</p>
            <dl className="mt-2 space-y-0.5 text-xs text-slate-500">
              {Object.entries(rule.inputs).map(([name, input]) => (
                <div key={name} className="flex gap-1.5">
                  <dt className="font-mono">{name}:</dt>
                  <dd>
                    {show(input.value)} ({input.state}
                    {input.overridden && ", overridden"})
                  </dd>
                </div>
              ))}
            </dl>
          </li>
        ))}
      </ul>
    </section>
  );
}
