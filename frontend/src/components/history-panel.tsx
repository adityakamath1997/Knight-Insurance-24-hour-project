"use client";

import { useEffect, useState } from "react";
import { listSubmissions } from "@/lib/api";
import type { OverallStatus, SortField, SortOrder, SubmissionListItem } from "@/lib/types";

const SORTS: { label: string; sort: SortField; order: SortOrder }[] = [
  { label: "Newest", sort: "created_at", order: "desc" },
  { label: "Oldest", sort: "created_at", order: "asc" },
  { label: "ID A-Z", sort: "id", order: "asc" },
  { label: "ID Z-A", sort: "id", order: "desc" },
  { label: "Status", sort: "status", order: "asc" },
  { label: "Business name", sort: "business_name", order: "asc" },
];

const STATUS_STYLES: Record<OverallStatus, string> = {
  READY_FOR_REVIEW: "bg-emerald-100 text-emerald-800",
  NEEDS_REVIEW: "bg-amber-100 text-amber-900",
};

export function HistoryPanel({
  selectedId,
  refreshKey,
  onSelect,
}: {
  selectedId: string | null;
  refreshKey: number;
  onSelect: (id: string) => void;
}) {
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [sortIndex, setSortIndex] = useState(0);
  const [items, setItems] = useState<SubmissionListItem[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const timer = setTimeout(() => setQuery(search), 250);
    return () => clearTimeout(timer);
  }, [search]);

  useEffect(() => {
    let current = true;
    const { sort, order } = SORTS[sortIndex];
    listSubmissions({ q: query, sort, order })
      .then((rows) => {
        if (!current) return;
        setItems(rows);
        setError(null);
      })
      .catch((caught) => {
        if (current) setError(caught instanceof Error ? caught.message : "Could not load history.");
      });
    return () => {
      current = false;
    };
  }, [query, sortIndex, refreshKey]);

  return (
    <aside className="card flex flex-col gap-3 lg:sticky lg:top-20 lg:max-h-[calc(100vh-6rem)]">
      <h2 className="text-sm font-semibold">History</h2>
      <input
        className="input"
        type="search"
        placeholder="Search by ID or business"
        aria-label="Search submissions"
        value={search}
        onChange={(event) => setSearch(event.target.value)}
      />
      <select
        className="input"
        aria-label="Sort submissions"
        value={sortIndex}
        onChange={(event) => setSortIndex(Number(event.target.value))}
      >
        {SORTS.map((option, index) => (
          <option key={option.label} value={index}>
            {option.label}
          </option>
        ))}
      </select>

      {error && (
        <p className="text-xs text-red-700" role="alert">
          {error}
        </p>
      )}
      {!error && items === null && <p className="text-xs text-slate-500">Loading...</p>}
      {!error && items?.length === 0 && (
        <p className="text-xs text-slate-500">
          {query.trim() ? "No submissions match." : "No submissions yet."}
        </p>
      )}

      <ul className="-mx-1 flex min-h-0 flex-col gap-1 overflow-y-auto px-1">
        {items?.map((item) => (
          <li key={item.id}>
            <button
              type="button"
              onClick={() => onSelect(item.id)}
              aria-current={item.id === selectedId}
              className={`w-full rounded-lg border px-3 py-2 text-left text-sm transition hover:bg-slate-50 ${
                item.id === selectedId ? "border-indigo-400 bg-indigo-50" : "border-slate-200"
              }`}
            >
              <div className="flex items-center justify-between gap-2">
                <span className="truncate font-medium">{item.business_name ?? "Unnamed business"}</span>
                <span className={`badge shrink-0 ${STATUS_STYLES[item.overall_status]}`}>
                  {item.overall_status === "READY_FOR_REVIEW" ? "Ready" : "Needs review"}
                </span>
              </div>
              <div className="mt-0.5 flex justify-between gap-2 text-xs text-slate-500">
                <span className="font-mono" title={item.id}>
                  {item.id.slice(0, 8)}
                </span>
                <time dateTime={item.created_at}>{new Date(item.created_at).toLocaleString()}</time>
              </div>
            </button>
          </li>
        ))}
      </ul>
    </aside>
  );
}
