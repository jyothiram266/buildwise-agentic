// Single place the browser talks to the API.
//
// The actor id is sent as a header rather than kept in a global: switching role in
// the demo must change what the API returns, and threading it through explicitly
// makes that impossible to forget.

import type {
  Actor,
  CaseResponse,
  CaseSummary,
  Dashboard,
  Replay,
  ReviewItem,
} from "./types";

const getBaseUrl = (): string => {
  const envUrl = import.meta.env.VITE_API_URL;
  if (!envUrl) return "";
  if (
    typeof window !== "undefined" &&
    window.location.hostname !== "localhost" &&
    window.location.hostname !== "127.0.0.1"
  ) {
    if (envUrl.includes("localhost") || envUrl.includes("127.0.0.1")) {
      return `${window.location.protocol}//${window.location.hostname}:8000`;
    }
  }
  return envUrl;
};

const BASE = getBaseUrl();


export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.status = status;
  }
}

async function request<T>(path: string, actorId: string | null, init?: RequestInit): Promise<T> {
  const headers: Record<string, string> = { "Content-Type": "application/json" };
  if (actorId) headers["X-Actor-Id"] = actorId;

  const response = await fetch(`${BASE}${path}`, { ...init, headers });
  if (!response.ok) {
    let detail = `${response.status} ${response.statusText}`;
    try {
      const body = await response.json();
      detail = body.detail ?? body.message ?? detail;
    } catch {
      // Response had no JSON body; the status line is the best we have.
    }
    throw new ApiError(detail, response.status);
  }
  return (await response.json()) as T;
}

export const api = {
  health: () => request<{ ok: boolean; llm_provider: string }>("/health", null),

  actors: () => request<Actor[]>("/api/actors", null),

  send: (actorId: string, text: string, channel = "web_chat", threadOf?: string) =>
    request<CaseResponse>("/api/cases", actorId, {
      method: "POST",
      body: JSON.stringify({ text, channel, thread_of: threadOf ?? null }),
    }),

  cases: (actorId: string, limit = 50) =>
    request<{ cases: CaseSummary[]; count: number }>(`/api/cases?limit=${limit}`, actorId),

  case: (actorId: string, caseId: string) =>
    request<Record<string, unknown>>(`/api/cases/${caseId}`, actorId),

  review: (actorId: string, tier?: number) =>
    request<{ items: ReviewItem[]; count: number }>(
      `/api/review${tier ? `?tier=${tier}` : ""}`,
      actorId,
    ),

  act: (
    actorId: string,
    reviewId: string,
    body: {
      action: "approve" | "edit_and_send" | "reject" | "reassign";
      edited_text?: string;
      rejection_reason?: string;
      assign_to?: string;
    },
  ) =>
    request<{ status: string; sent_text: string | null; approval_token: string | null }>(
      `/api/review/${reviewId}/act`,
      actorId,
      { method: "POST", body: JSON.stringify(body) },
    ),

  dashboard: (actorId: string, windowDays = 30) =>
    request<Dashboard>(`/api/dashboard?window_days=${windowDays}`, actorId),

  replay: (actorId: string, caseId: string) =>
    request<Replay>(`/api/audit/${caseId}`, actorId),

  connectorHealth: () =>
    request<{ connectors: { system: string; ok: boolean; detail?: string }[] }>(
      "/api/health/connectors",
      null,
    ),
};
