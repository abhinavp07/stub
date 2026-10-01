import type { BudgetStatus, CategoryTotal, TrendPoint } from "./types";

/** A donut reads as part-to-whole only with a handful of segments: show the largest
 *  categories and fold the rest into one neutral "Everything else" slice. */
export const MAX_DONUT_SEGMENTS = 6;
export const FOLD_COLOR = "#b5b4ad";
export const SERIES_COLOR = "#2a78d6"; // categorical slot 1, for single-series charts

export interface DonutSegment {
  key: string;
  name: string;
  color: string;
  value: number;
  share: number; // 0-1
  receiptCount: number;
}

export function donutSegments(items: CategoryTotal[], max = MAX_DONUT_SEGMENTS): DonutSegment[] {
  // Refunds can make a category net-negative; a donut can only show positive parts.
  const positive = items
    .map((i) => ({ ...i, value: Number(i.total) }))
    .filter((i) => i.value > 0)
    .sort((a, b) => b.value - a.value);
  const sum = positive.reduce((s, i) => s + i.value, 0);
  if (sum === 0) return [];

  const keep = positive.length > max ? positive.slice(0, max - 1) : positive;
  const rest = positive.slice(keep.length);
  const segments: DonutSegment[] = keep.map((i) => ({
    key: i.category_id ?? "uncategorized",
    name: i.name,
    color: i.color,
    value: i.value,
    share: i.value / sum,
    receiptCount: i.receipt_count,
  }));
  if (rest.length > 0) {
    const value = rest.reduce((s, i) => s + i.value, 0);
    segments.push({
      key: "everything-else",
      name: `Everything else (${rest.length})`,
      color: FOLD_COLOR,
      value,
      share: value / sum,
      receiptCount: rest.reduce((s, i) => s + i.receipt_count, 0),
    });
  }
  return segments;
}

export interface TrendBar {
  month: string; // YYYY-MM
  label: string; // "Mar" or "Mar 24" for January / first bar
  value: number;
  receiptCount: number;
}

/** "Mar", or "Mar ’24" with the year (an apostrophe so it can't read as "March 24th"). */
export function monthLabel(month: string, withYear = false): string {
  const [y, m] = month.split("-").map(Number);
  const short = new Date(y!, m! - 1, 1).toLocaleDateString(undefined, { month: "short" });
  return withYear ? `${short} ’${String(y).slice(-2)}` : short;
}

/** "March 2024", for headings. */
export function monthName(month: string): string {
  const [y, m] = month.split("-").map(Number);
  return new Date(y!, m! - 1, 1).toLocaleDateString(undefined, { month: "long", year: "numeric" });
}

export function trendBars(points: TrendPoint[]): TrendBar[] {
  return points.map((p, i) => ({
    month: p.month,
    // Show the year where it changes so a 12-month window spanning New Year reads clearly.
    label: monthLabel(p.month, i === 0 || p.month.endsWith("-01")),
    value: Number(p.total),
    receiptCount: p.receipt_count,
  }));
}

export function hasSpending(points: TrendPoint[]): boolean {
  return points.some((p) => p.receipt_count > 0);
}

/** Status palette (never reused for series). Always shown with an icon and a label. */
export const BUDGET_TONES: Record<
  BudgetStatus,
  { fill: string; track: string; label: string; icon: string; text: string }
> = {
  ok: { fill: "#2a78d6", track: "#cde2fb", label: "On track", icon: "✓", text: "text-gray-600" },
  warning: {
    fill: "#fab219",
    track: "#fdecc6",
    label: "Near limit",
    icon: "▲",
    text: "text-amber-800",
  },
  over: {
    fill: "#d03b3b",
    track: "#f6d3d3",
    label: "Over budget",
    icon: "!",
    text: "text-red-700",
  },
};

/** Width of the filled part of a budget bar, clamped to the track. */
export function meterWidth(percentUsed: string | number): number {
  const n = Number(percentUsed);
  if (!Number.isFinite(n) || n <= 0) return 0;
  return Math.min(100, n);
}
