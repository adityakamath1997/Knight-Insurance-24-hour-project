"use client";

import { useState } from "react";

export function SubmissionForm({
  busy,
  onSubmit,
}: {
  busy: boolean;
  onSubmit: (emailText: string, files: File[]) => void;
}) {
  const [emailText, setEmailText] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const empty = !emailText.trim() && files.length === 0;

  return (
    <form
      className="card flex flex-col gap-4"
      onSubmit={(event) => {
        event.preventDefault();
        onSubmit(emailText, files);
      }}
    >
      <label className="flex flex-col gap-1.5">
        <span className="text-sm font-medium">Broker email</span>
        <textarea
          className="input min-h-36"
          placeholder="Paste the broker email here (optional)"
          value={emailText}
          onChange={(event) => setEmailText(event.target.value)}
          disabled={busy}
        />
      </label>
      <label className="flex flex-col gap-1.5">
        <span className="text-sm font-medium">Packet files</span>
        <input
          className="block w-full text-sm text-slate-600 file:mr-3 file:rounded-lg file:border-0 file:bg-indigo-50 file:px-3.5 file:py-2 file:text-sm file:font-medium file:text-indigo-700 hover:file:bg-indigo-100"
          type="file"
          multiple
          disabled={busy}
          onChange={(event) => setFiles(Array.from(event.target.files ?? []))}
        />
        {files.length > 0 && (
          <span className="text-xs text-slate-500">{files.map((file) => file.name).join(", ")}</span>
        )}
      </label>
      <button className="btn-primary self-start" disabled={busy || empty}>
        {busy ? "Processing…" : "Review submission"}
      </button>
    </form>
  );
}
