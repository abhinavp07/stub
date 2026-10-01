import { filtersToParams } from "./filters";
import type {
  Budget,
  BudgetInput,
  ByCategory,
  Category,
  CategoryInput,
  LineItemInput,
  LoginRequest,
  InsightsSummary,
  Page,
  ReceiptDetail,
  ReceiptFilters,
  ReceiptSummary,
  ReceiptUpdate,
  SignupRequest,
  Trend,
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
  list: (filters: ReceiptFilters = {}, cursor?: string | null, limit = 25) => {
    const qs = filtersToParams(filters);
    if (cursor) qs.set("cursor", cursor);
    qs.set("limit", String(limit));
    return request<Page<ReceiptSummary>>(`/receipts?${qs.toString()}`);
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

export const categoriesApi = {
  list: () => request<Category[]>("/categories"),
  create: (body: CategoryInput) =>
    request<Category>("/categories", { method: "POST", json: { ...body } }),
  update: (id: string, body: CategoryInput) =>
    request<Category>(`/categories/${id}`, { method: "PATCH", json: { ...body } }),
  remove: (id: string) => request<void>(`/categories/${id}`, { method: "DELETE" }),
};

export const insightsApi = {
  summary: (month?: string) =>
    request<InsightsSummary>(`/insights/summary${month ? `?month=${month}` : ""}`),
  byCategory: (from?: string, to?: string) => {
    const qs = new URLSearchParams();
    if (from) qs.set("from", from);
    if (to) qs.set("to", to);
    return request<ByCategory>(`/insights/by-category?${qs.toString()}`);
  },
  trend: (months = 12) => request<Trend>(`/insights/trend?months=${months}`),
};

export const budgetsApi = {
  list: () => request<Budget[]>("/budgets"),
  set: (categoryId: string, body: BudgetInput) =>
    request<Budget>(`/budgets/${categoryId}`, { method: "PUT", json: { ...body } }),
  remove: (categoryId: string) => request<void>(`/budgets/${categoryId}`, { method: "DELETE" }),
};

type ExportParams = { from?: string; to?: string; category_id?: string };

function exportUrl(format: "csv" | "pdf", params: ExportParams) {
  const qs = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) if (v) qs.set(k, v);
  const query = qs.toString();
  return `/api/export/${format}${query ? `?${query}` : ""}`;
}

/** Download links for exports (plain links; the auth cookie goes along). */
export const exportCsvUrl = (params: ExportParams) => exportUrl("csv", params);
export const exportPdfUrl = (params: ExportParams) => exportUrl("pdf", params);
