import type { FieldName, FieldValue, SubmissionDetail } from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function request(path: string, init?: RequestInit): Promise<SubmissionDetail> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, init);
  } catch {
    throw new Error(`Cannot reach the backend at ${BASE_URL}.`);
  }
  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const body = await response.json();
      if (typeof body.detail === "string") message = body.detail;
      else if (Array.isArray(body.detail))
        message = body.detail.map((item: { msg: string }) => item.msg).join("; ");
    } catch {
      // Keep the status-only message.
    }
    throw new Error(message);
  }
  return response.json();
}

function json(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export function createSubmission(emailText: string, files: File[]) {
  const form = new FormData();
  if (emailText.trim()) form.append("email_text", emailText);
  for (const file of files) form.append("files", file);
  return request("/submissions", { method: "POST", body: form });
}

export function overrideField(
  id: string,
  field: FieldName,
  value: FieldValue,
  note: string | null,
) {
  return request(`/submissions/${id}/fields/${field}`, json("PATCH", { value, note }));
}

export function saveDraft(id: string, body: string) {
  return request(`/submissions/${id}/draft`, json("PATCH", { body }));
}

export function regenerateNarrative(id: string) {
  return request(`/submissions/${id}/narrative/regenerate`, { method: "POST" });
}

export function sendMessage(id: string, message: string) {
  return request(`/submissions/${id}/narrative/messages`, json("POST", { message }));
}
