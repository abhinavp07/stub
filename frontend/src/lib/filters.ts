import type { ReceiptFilters } from "./types";

const STRING_KEYS = [
  "q",
  "category_id",
  "date_from",
  "date_to",
  "min_total",
  "max_total",
  "tag",
] as const;
const STATUSES = ["processing", "ready", "failed"] as const;

/** Filters -> URL query params, omitting empty values and defaults. */
export function filtersToParams(filters: ReceiptFilters): URLSearchParams {
  const params = new URLSearchParams();
  for (const key of STRING_KEYS) {
    const v = filters[key]?.trim();
    if (v) params.set(key, v);
  }
  if (filters.status) params.set("status", filters.status);
  if (filters.needs_review !== undefined) params.set("needs_review", String(filters.needs_review));
  if (filters.sort && filters.sort !== "purchase_date") params.set("sort", filters.sort);
  return params;
}

/** URL query params -> filters, dropping anything malformed. Keeps the list page shareable
 *  (e.g. the dashboard links to /receipts?needs_review=true). */
export function paramsToFilters(params: URLSearchParams): ReceiptFilters {
  const filters: ReceiptFilters = {};
  for (const key of STRING_KEYS) {
    const v = params.get(key)?.trim();
    if (v) filters[key] = v;
  }
  for (const key of ["date_from", "date_to"] as const) {
    if (filters[key] && !/^\d{4}-\d{2}-\d{2}$/.test(filters[key]!)) delete filters[key];
  }
  for (const key of ["min_total", "max_total"] as const) {
    if (filters[key] && !/^\d+(\.\d{1,2})?$/.test(filters[key]!)) delete filters[key];
  }
  const status = params.get("status");
  if (status && (STATUSES as readonly string[]).includes(status)) {
    filters.status = status as ReceiptFilters["status"];
  }
  const review = params.get("needs_review");
  if (review === "true" || review === "false") filters.needs_review = review === "true";
  if (params.get("sort") === "total") filters.sort = "total";
  return filters;
}

/** How many filters are active, not counting search and sort. */
export function activeFilterCount(f: ReceiptFilters): number {
  return [
    f.category_id,
    f.date_from,
    f.date_to,
    f.min_total,
    f.max_total,
    f.status,
    f.needs_review,
    f.tag,
  ].filter((v) => v !== undefined && v !== "").length;
}
