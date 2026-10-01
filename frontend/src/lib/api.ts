import type {
  LineItemInput,
  LoginRequest,
  Page,
  ReceiptDetail,
  ReceiptSummary,
  ReceiptUpdate,
  SignupRequest,
  UploadUrlRequest,
  UploadUrlResponse,
  User,
} from "./types";

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

type Json = Record<string, unknown> | unknown[];

interface RequestOptions extends Omit<RequestInit, "body"> {
  json?: Json;
}

/** Typed fetch wrapper. Paths are relative to /api, which Next.js proxies to FastAPI. */
export async function request<T>(path: string, { json, headers, ...init }: RequestOptions = {}) {
  const res = await fetch(`/api${path}`, {
    credentials: "include",
    ...init,
    headers: json === undefined ? headers : { "Content-Type": "application/json", ...headers },
    body: json === undefined ? undefined : JSON.stringify(json),
  });

  if (!res.ok) {
    let detail = res.statusText || "Request failed";
    try {
      const body: unknown = await res.json();
      if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
        detail = body.detail;
      }
    } catch {
      // Non-JSON error body; fall back to statusText.
    }
    // Session expired mid-use: clear the stale cookie (middleware would otherwise bounce us
    // straight back) and send the user to log in. Auth endpoints handle 401 inline.
    if (res.status === 401 && !path.startsWith("/auth/") && typeof window !== "undefined") {
      await fetch("/api/auth/logout", { method: "POST", credentials: "include" }).catch(() => {});
      const next = encodeURIComponent(window.location.pathname + window.location.search);
      window.location.assign(`/login?next=${next}`);
    }
    throw new ApiError(res.status, detail);
  }
  if (res.status === 204) return undefined as T;
  return (await res.json()) as T;
}

export const authApi = {
  me: () => request<User>("/auth/me"),
  login: (body: LoginRequest) =>
    request<User>("/auth/login", { method: "POST", json: { ...body } }),
  signup: (body: SignupRequest) =>
    request<User>("/auth/signup", { method: "POST", json: { ...body } }),
  logout: () => request<void>("/auth/logout", { method: "POST" }),
};

export const receiptsApi = {
  list: (params: { cursor?: string | null; limit?: number } = {}) => {
    const qs = new URLSearchParams();
    if (params.cursor) qs.set("cursor", params.cursor);
    if (params.limit) qs.set("limit", String(params.limit));
    const query = qs.toString();
    return request<Page<ReceiptSummary>>(`/receipts${query ? `?${query}` : ""}`);
  },
  get: (id: string) => request<ReceiptDetail>(`/receipts/${id}`),
  uploadUrl: (body: UploadUrlRequest) =>
    request<UploadUrlResponse>("/receipts/upload-url", { method: "POST", json: { ...body } }),
  complete: (id: string) => request<ReceiptDetail>(`/receipts/${id}/complete`, { method: "POST" }),
  update: (id: string, body: ReceiptUpdate) =>
    request<ReceiptDetail>(`/receipts/${id}`, { method: "PATCH", json: { ...body } }),
  replaceLineItems: (id: string, items: LineItemInput[]) =>
    request<ReceiptDetail>(`/receipts/${id}/line-items`, { method: "PUT", json: items }),
  reprocess: (id: string) =>
    request<ReceiptDetail>(`/receipts/${id}/reprocess`, { method: "POST" }),
  remove: (id: string) => request<void>(`/receipts/${id}`, { method: "DELETE" }),
};
