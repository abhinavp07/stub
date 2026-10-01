import { describe, expect, it } from "vitest";

import { formatDate, formatMoney } from "@/lib/format";

describe("formatMoney", () => {
  it("formats decimal strings with the given currency", () => {
    expect(formatMoney("1234.5", "USD")).toBe(
      new Intl.NumberFormat(undefined, { style: "currency", currency: "USD" }).format(1234.5),
    );
    expect(formatMoney("10.00", "EUR")).toContain("10");
  });

  it("shows a dash for missing values", () => {
    expect(formatMoney(null)).toBe("—");
    expect(formatMoney("")).toBe("—");
  });
});

describe("formatDate", () => {
  it("does not shift the calendar day across timezones", () => {
    expect(formatDate("2024-03-01")).toBe(
      new Date(2024, 2, 1).toLocaleDateString(undefined, {
        year: "numeric",
        month: "short",
        day: "numeric",
      }),
    );
  });

  it("handles null", () => {
    expect(formatDate(null)).toBe("—");
  });
});
