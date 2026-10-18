import type {
  FieldName,
  FieldValue,
  ProgressEvent,
  SortField,
  SortOrder,
  SubmissionDetail,
  SubmissionListItem,
} from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function failureMessage(response: Response): Promise<string> {
  let message = `Request failed (${response.status}).`;
  try {
    const body = await response.json();
    if (typeof body.detail === "string") message = body.detail;
    else if (Array.isArray(body.detail))
      message = body.detail.map((item: { msg: string }) => item.msg).join("; ");
  } catch {
    // Keep the status-only message.
  }
  return message;
}

async function send(path: string, init?: RequestInit): Promise<Response> {
  let response: Response;
  try {
    response = await fetch(`${BASE_URL}${path}`, init);
  } catch {
    throw new Error(`Cannot reach the backend at ${BASE_URL}.`);
  }
  if (!response.ok) throw new Error(await failureMessage(response));
  return response;
}

async function request<T = SubmissionDetail>(path: string, init?: RequestInit): Promise<T> {
  return (await send(path, init)).json();
}

function json(method: string, body: unknown): RequestInit {
  return {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export function createSubmission(emailText: string, files: File[]) {
  return request("/submissions", { method: "POST", body: packetForm(emailText, files) });
}

function packetForm(emailText: string, files: File[]) {
  const form = new FormData();
  if (emailText.trim()) form.append("email_text", emailText);
  for (const file of files) form.append("files", file);
  return form;
}

// Server-sent events arrive as blocks of "event:" and "data:" lines separated by a blank line.
function parseBlock(block: string): { event: string; data: string } | null {
  let event = "message";
  const data: string[] = [];
  for (const line of block.split("\n")) {
    if (line.startsWith("event:")) event = line.slice(6).trim();
    else if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
  }
  return data.length ? { event, data: data.join("\n") } : null;
}

export async function streamSubmission(
  emailText: string,
  files: File[],
  onProgress: (event: ProgressEvent) => void,
): Promise<SubmissionDetail> {
  const response = await send("/submissions/stream", {
    method: "POST",
    body: packetForm(emailText, files),
  });
  if (!response.body) throw new Error("The backend did not return a stream.");
  const reader = response.body.pipeThrough(new TextDecoderStream()).getReader();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (value) buffer += value.replace(/\r\n/g, "\n");
    const blocks = buffer.split("\n\n");
    buffer = done ? "" : (blocks.pop() ?? "");
    for (const block of blocks) {
      const message = parseBlock(block);
      if (!message) continue;
      const payload = JSON.parse(message.data);
      if (message.event === "progress") onProgress(payload as ProgressEvent);
      else if (message.event === "result") return payload as SubmissionDetail;
      else if (message.event === "error") throw new Error(payload.detail ?? "Review failed.");
    }
    if (done) throw new Error("The connection closed before the review finished.");
  }
}

export function listSubmissions(params: {
  q: string;
  sort: SortField;
  order: SortOrder;
}): Promise<SubmissionListItem[]> {
  const query = new URLSearchParams({ sort: params.sort, order: params.order });
  if (params.q.trim()) query.set("q", params.q.trim());
  return request<SubmissionListItem[]>(`/submissions?${query}`);
}

export function getSubmission(id: string) {
  return request(`/submissions/${encodeURIComponent(id)}`);
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
