import { describe, expect, it } from "vitest";

import { activeFilterCount, filtersToParams, paramsToFilters } from "@/lib/filters";
import type { ReceiptFilters } from "@/lib/types";

describe("filters <-> URL params", () => {
  it("round-trips every filter", () => {
    const filters: ReceiptFilters = {
      q: "kroger",
      category_id: "none",
      date_from: "2024-01-01",
      date_to: "2024-12-31",
      min_total: "10",
      max_total: "99.50",
      status: "ready",
      needs_review: true,
      tag: "work trip",
      sort: "total",
    };
    const params = filtersToParams(filters);
    expect(paramsToFilters(new URLSearchParams(params.toString()))).toEqual(filters);
  });

  it("omits empty values and the default sort", () => {
    expect(
      filtersToParams({ q: "  ", tag: "", sort: "purchase_date", needs_review: false }).toString(),
    ).toBe("needs_review=false");
  });

  it("drops malformed values from the URL", () => {
    const f = paramsToFilters(
      new URLSearchParams(
        "date_from=yesterday&min_total=abc&status=bogus&needs_review=maybe&sort=x&max_total=5",
      ),
    );
    expect(f).toEqual({ max_total: "5" });
  });

  it("counts active filters, ignoring search and sort", () => {
    expect(activeFilterCount({ q: "x", sort: "total" })).toBe(0);
    expect(activeFilterCount({ needs_review: false, tag: "a", category_id: "c" })).toBe(3);
  });
});
