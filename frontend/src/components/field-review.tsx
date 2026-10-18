"use client";

import { useState } from "react";
import { overrideField } from "@/lib/api";
import type {
  FieldName,
  FieldValue,
  ReviewedField,
  SubmissionDetail,
} from "@/lib/types";

const LABELS: Record<FieldName, string> = {
  business_name: "Business name",
  requested_effective_date: "Requested effective date",
  garaging_state: "Garaging state",
  operations_description: "Operations description",
  declared_vehicle_count: "Declared vehicle count",
  operating_radius_miles: "Operating radius (miles)",
  hazardous_materials: "Hazardous materials",
  loss_runs_present: "Loss runs present",
  schedule_vehicle_count: "Schedule vehicle count",
};

const ORDER = Object.keys(LABELS) as FieldName[];

type InputKind = "text" | "textarea" | "date" | "int" | "number" | "bool";

const KINDS: Record<FieldName, InputKind> = {
  business_name: "text",
  requested_effective_date: "date",
  garaging_state: "text",
  operations_description: "textarea",
  declared_vehicle_count: "int",
  operating_radius_miles: "number",
  hazardous_materials: "bool",
  loss_runs_present: "bool",
  schedule_vehicle_count: "int",
};

function toText(value: FieldValue): string {
  if (value === null) return "";
  return String(value);
}

// The backend validates overrides; this only turns form text into the typed JSON value.
function toTyped(kind: InputKind, text: string): FieldValue {
  const trimmed = text.trim();
  if (kind === "bool") return trimmed === "true";
  if (kind === "int" || kind === "number") {
    const parsed = Number(trimmed);
    if (trimmed === "" || !Number.isFinite(parsed)) {
      throw new Error("Enter a number.");
    }
    return parsed;
  }
  return trimmed;
}

function show(value: FieldValue) {
  if (value === null) return "—";
  if (typeof value === "boolean") return value ? "Yes" : "No";
  return String(value);
}

const STATE_STYLES: Record<string, string> = {
  KNOWN: "bg-emerald-100 text-emerald-800",
  MISSING: "bg-amber-100 text-amber-800",
  CONFLICT: "bg-red-100 text-red-800",
  INVALID: "bg-red-100 text-red-800",
};

function FieldRow({
  field,
  submissionId,
  onUpdate,
}: {
  field: ReviewedField;
  submissionId: string;
  onUpdate: (detail: SubmissionDetail) => void;
}) {
  const kind = KINDS[field.name];
  const initial = toText(field.value);
  const [text, setText] = useState(initial);
  const [note, setNote] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const dirty = text !== initial;
  const evidenceCount = field.candidates.reduce((sum, c) => sum + c.evidence.length, 0);

  async function save() {
    setError(null);
    setSaving(true);
    try {
      const value = toTyped(kind, text);
      onUpdate(await overrideField(submissionId, field.name, value, note.trim() || null));
    } catch (caught) {
      setError(caught instanceof Error ? caught.message : "Override failed.");
      setSaving(false);
    }
  }

  const inputId = `field-${field.name}`;

  return (
    <li className="card flex flex-col gap-2">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <label htmlFor={inputId} className="font-medium">
          {LABELS[field.name]}
        </label>
        <div className="flex gap-1.5">
          {field.override && <span className="badge bg-indigo-100 text-indigo-800">HUMAN OVERRIDE</span>}
          <span className={`badge ${STATE_STYLES[field.state]}`}>{field.state}</span>
        </div>
      </div>

      {kind === "bool" ? (
        <select id={inputId} className="input" value={text} onChange={(event) => setText(event.target.value)}>
          <option value="">Not set</option>
          <option value="true">Yes</option>
          <option value="false">No</option>
        </select>
      ) : kind === "textarea" ? (
        <textarea
          id={inputId}
          className="input min-h-24"
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
      ) : (
        <input
          id={inputId}
          className="input"
          type={kind === "date" ? "date" : kind === "text" ? "text" : "number"}
          step={kind === "number" ? "any" : undefined}
          min={kind === "int" || kind === "number" ? 0 : undefined}
          value={text}
          onChange={(event) => setText(event.target.value)}
        />
      )}

      {field.override && (
        <p className="text-xs text-slate-600">
          Original: {field.override.original_state} / {show(field.override.original_value)}
          {field.override.note && <> · note: {field.override.note}</>}
        </p>
      )}

      {field.state === "CONFLICT" && (
        <ul className="rounded-lg bg-red-50 p-2 text-xs text-red-900">
          {field.candidates.map((candidate, index) => (
            <li key={index}>
              {candidate.source}: <strong>{show(candidate.value)}</strong>
              {candidate.raw_value !== null && <> (raw “{candidate.raw_value}”)</>}
            </li>
          ))}
        </ul>
      )}

      {field.state === "MISSING" && (
        <p className="rounded-lg bg-amber-50 p-2 text-xs text-amber-900">
          Checked: {field.inspected_sources.length ? field.inspected_sources.join(", ") : "no sources"}
          {field.name === "loss_runs_present" && (
            <>
              {" "}
              · Attachments: {field.attachment_inventory.length ? field.attachment_inventory.join(", ") : "none"}
            </>
          )}
        </p>
      )}

      {evidenceCount > 0 && (
        <details className="text-xs">
          <summary className="cursor-pointer text-slate-600">Evidence ({evidenceCount})</summary>
          <ul className="mt-1.5 space-y-2">
            {field.candidates.map((candidate, index) => (
              <li key={index}>
                <div className="font-medium text-slate-700">
                  {candidate.source} · {candidate.state}
                  {candidate.raw_value !== null && <> · raw “{candidate.raw_value}”</>}
                </div>
                {candidate.evidence.map((item, i) => (
                  <blockquote key={i} className="mt-1 border-l-2 border-indigo-200 pl-2 text-slate-700">
                    <div className="text-slate-500">
                      {item.source_file} · {item.locator}
                    </div>
                    {item.excerpt_or_observation}
                  </blockquote>
                ))}
              </li>
            ))}
          </ul>
        </details>
      )}

      {dirty && (
        <div className="flex flex-col gap-2 border-t border-slate-100 pt-2">
          <input
            className="input"
            placeholder="Reason for the correction (optional)"
            value={note}
            onChange={(event) => setNote(event.target.value)}
          />
          <div className="flex gap-2">
            <button className="btn-primary" disabled={saving || (kind === "bool" && text === "")} onClick={save}>
              {saving ? "Saving…" : "Save correction"}
            </button>
            <button className="btn" disabled={saving} onClick={() => { setText(initial); setError(null); }}>
              Reset
            </button>
          </div>
        </div>
      )}
      {error && <p className="text-xs text-red-700">{error}</p>}
    </li>
  );
}

export function FieldReview({
  detail,
  onUpdate,
}: {
  detail: SubmissionDetail;
  onUpdate: (detail: SubmissionDetail) => void;
}) {
  return (
    <section>
      <h2 className="mb-1 text-xl font-semibold tracking-tight">Extracted fields</h2>
      <p className="mb-3 text-sm text-slate-500">
        Edit any value to correct it. Corrections are saved as labeled overrides; the original value and
        evidence stay visible, and the rules re-run.
      </p>
      <ul className="grid gap-3 md:grid-cols-2 lg:grid-cols-3">
        {ORDER.map((name) => {
          const field = detail.fields[name];
          // Remount after a save so the edit box shows the new effective value.
          const key = `${name}:${field.override?.created_at ?? "none"}`;
          return <FieldRow key={key} field={field} submissionId={detail.id} onUpdate={onUpdate} />;
        })}
      </ul>
    </section>
  );
}
