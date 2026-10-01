import { render, screen, within } from "@testing-library/react";
import { cloneElement, type ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";

import { BudgetMeter } from "@/components/charts/BudgetMeter";
import { SpendingDonut } from "@/components/charts/SpendingDonut";
import { TrendChart } from "@/components/charts/TrendChart";
import { donutSegments, FOLD_COLOR, meterWidth, trendBars } from "@/lib/charts";
import type { Budget, CategoryTotal, TrendPoint } from "@/lib/types";

// jsdom has no layout, so ResponsiveContainer measures 0x0 and draws nothing. Give charts a
// fixed size instead so the SVG marks can be asserted on.
vi.mock("recharts", async (importOriginal) => {
  const actual = await importOriginal<typeof import("recharts")>();
  return {
    ...actual,
    ResponsiveContainer: ({ children }: { children: ReactElement<{ width?: number }> }) =>
      cloneElement(children, { width: 600, height: 224 } as object),
  };
});

function months(totals: (string | null)[], start = "2024-01"): TrendPoint[] {
  const [y, m] = start.split("-").map(Number);
  return totals.map((t, i) => {
    const d = new Date(y!, m! - 1 + i, 1);
    const month = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}`;
    return { month, total: t ?? "0.00", receipt_count: t ? 1 : 0, by_category: null };
  });
}

const cat = (name: string, total: string, n = 1): CategoryTotal => ({
  category_id: name.toLowerCase(),
  name,
  color: "#2a78d6",
  total,
  receipt_count: n,
});

describe("TrendChart", () => {
  it("shows an empty state with zero months of data", () => {
    render(<TrendChart points={months(Array(12).fill(null))} currency="USD" />);
    expect(screen.getByText(/monthly totals will appear here/i)).toBeInTheDocument();
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });

  it("renders a single month of data", () => {
    const { container } = render(
      <TrendChart points={months([...Array(11).fill(null), "42.50"])} currency="USD" />,
    );
    expect(screen.getByRole("img", { name: /monthly spending/i })).toBeInTheDocument();
    // One visible bar; the empty months are zero-height.
    const bars = [...container.querySelectorAll(".recharts-bar-rectangle path")];
    expect(bars.filter((b) => Number(b.getAttribute("height")) > 0)).toHaveLength(1);
    const rows = within(screen.getByRole("table")).getAllByRole("row");
    expect(rows).toHaveLength(13); // header + 12 months, empty months included
    expect(rows[12]).toHaveTextContent("$42.50");
  });

  it("renders many months, including a refund month below zero", () => {
    const totals = ["10.00", "20.00", "-5.00", "300.25", "0.99", "12.00"];
    const { container } = render(<TrendChart points={months(totals, "2023-10")} currency="USD" />);
    expect(container.querySelectorAll(".recharts-bar-rectangle path")).toHaveLength(6);
    const rows = within(screen.getByRole("table")).getAllByRole("row");
    expect(rows).toHaveLength(7);
    expect(rows[3]).toHaveTextContent("-$5.00");
  });

  it("labels the year where it changes", () => {
    const bars = trendBars(months(["1", "1", "1", "1"], "2023-11"));
    expect(bars.map((b) => b.label.includes("23") || b.label.includes("24"))).toEqual([
      true, // first bar
      false,
      true, // January
      false,
    ]);
  });
});

describe("SpendingDonut", () => {
  it("shows an empty state when there's no positive spending", () => {
    render(<SpendingDonut items={[cat("Refunds", "-5.00")]} total="-5.00" currency="USD" />);
    expect(screen.getByText(/no spending recorded/i)).toBeInTheDocument();
  });

  it("renders one category", () => {
    const { container } = render(
      <SpendingDonut items={[cat("Groceries", "50.00", 2)]} total="50.00" currency="USD" />,
    );
    expect(container.querySelectorAll(".recharts-pie-sector")).toHaveLength(1);
    expect(screen.getByRole("img", { name: /Groceries 100%/ })).toBeInTheDocument();
    const row = screen.getByRole("row", { name: /Groceries/ });
    expect(row).toHaveTextContent("$50.00");
    expect(row).toHaveTextContent("100%");
  });

  it("folds the tail into 'Everything else' beyond six segments", () => {
    const items = ["A", "B", "C", "D", "E", "F", "G", "H"].map((n, i) =>
      cat(n, String(100 - i * 10)),
    );
    const segments = donutSegments(items);
    expect(segments).toHaveLength(6);
    expect(segments.map((s) => s.name)).toEqual(["A", "B", "C", "D", "E", "Everything else (3)"]);
    expect(segments[5]!.value).toBe(50 + 40 + 30);
    expect(segments[5]!.color).toBe(FOLD_COLOR);
    expect(segments.reduce((s, x) => s + x.share, 0)).toBeCloseTo(1);
  });

  it("doesn't fold when exactly six categories", () => {
    const items = ["A", "B", "C", "D", "E", "F"].map((n) => cat(n, "10"));
    expect(donutSegments(items).map((s) => s.name)).toEqual(["A", "B", "C", "D", "E", "F"]);
  });
});

describe("BudgetMeter", () => {
  const budget = (status: Budget["status"], percent: string): Budget => ({
    category_id: "c",
    category_name: "Groceries",
    color: "#2a78d6",
    monthly_limit: "100.00",
    alert_threshold_pct: 80,
    month: "2024-03",
    spent: percent,
    remaining: String(100 - Number(percent)),
    percent_used: percent,
    status,
  });

  it.each([
    ["ok", "50.0", "On track", "#2a78d6"],
    ["warning", "80.0", "Near limit", "#fab219"],
    ["over", "123.4", "Over budget", "#d03b3b"],
  ] as const)("%s at %s%% is labeled and colored", (status, percent, label, fill) => {
    render(<BudgetMeter budget={budget(status, percent)} currency="USD" />);
    const meter = screen.getByRole("meter", { name: "Groceries budget" });
    expect(meter).toHaveAttribute("data-status", status);
    expect(meter).toHaveAttribute("aria-valuetext", `${percent}% used, ${label}`);
    expect((meter.firstChild as HTMLElement).style.backgroundColor).toBe(hexToRgb(fill));
    expect(screen.getByText(new RegExp(label))).toBeInTheDocument();
  });

  it("clamps the fill to the track", () => {
    expect(meterWidth("123.4")).toBe(100);
    expect(meterWidth("-3")).toBe(0);
    expect(meterWidth("42.5")).toBe(42.5);
  });

  it("says how much over budget", () => {
    render(<BudgetMeter budget={budget("over", "123.4")} currency="USD" />);
    expect(screen.getByText("$23.40 over")).toBeInTheDocument();
  });
});

function hexToRgb(hex: string): string {
  const n = parseInt(hex.slice(1), 16);
  return `rgb(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255})`;
}
