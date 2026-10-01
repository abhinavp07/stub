"use client";

import {
  Bar,
  BarChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { SERIES_COLOR, hasSpending, monthName, trendBars, type TrendBar } from "@/lib/charts";
import { formatMoney } from "@/lib/format";
import type { TrendPoint } from "@/lib/types";

function compactMoney(value: number, currency: string): string {
  return new Intl.NumberFormat(undefined, {
    style: "currency",
    currency,
    notation: "compact",
    maximumFractionDigits: 1,
  }).format(value);
}

/** Monthly totals as a single-series column chart (one hue; the title names the series). */
export function TrendChart({ points, currency }: { points: TrendPoint[]; currency: string }) {
  const bars = trendBars(points);
  if (!hasSpending(points)) {
    return (
      <p className="flex h-56 items-center justify-center text-center text-sm text-gray-500">
        Your monthly totals will appear here once you have receipts with dates and totals.
      </p>
    );
  }

  return (
    <div className="space-y-2">
      <div className="h-56" role="img" aria-label="Monthly spending, last 12 months. Table below.">
        <ResponsiveContainer
          width="100%"
          height="100%"
          initialDimension={{ width: 600, height: 224 }}
        >
          <BarChart
            data={bars}
            margin={{ top: 8, right: 4, bottom: 0, left: 4 }}
            barCategoryGap="20%"
          >
            <CartesianGrid vertical={false} stroke="#ecebe8" />
            <XAxis
              dataKey="label"
              tickLine={false}
              axisLine={false}
              tick={{ fontSize: 11, fill: "#6b6a65" }}
              interval="preserveStartEnd"
              minTickGap={8}
            />
            <YAxis
              width={52}
              tickLine={false}
              axisLine={false}
              tick={{ fontSize: 11, fill: "#6b6a65" }}
              tickFormatter={(v: number) => compactMoney(v, currency)}
            />
            <ReferenceLine y={0} stroke="#c8c7c1" />
            <Tooltip cursor={{ fill: "#f2f1ee" }} content={<TrendTooltip currency={currency} />} />
            <Bar
              dataKey="value"
              fill={SERIES_COLOR}
              radius={[4, 4, 0, 0]}
              maxBarSize={36}
              isAnimationActive={false}
            />
          </BarChart>
        </ResponsiveContainer>
      </div>
      <details className="text-sm">
        <summary className="cursor-pointer rounded text-gray-600 hover:text-gray-900 focus-visible:outline-2 focus-visible:outline-blue-600">
          Show as table
        </summary>
        <table className="mt-2 w-full">
          <caption className="sr-only">Monthly spending</caption>
          <thead>
            <tr className="border-b border-gray-200 text-left text-xs text-gray-500">
              <th scope="col" className="py-1 font-medium">
                Month
              </th>
              <th scope="col" className="py-1 text-right font-medium">
                Receipts
              </th>
              <th scope="col" className="py-1 text-right font-medium">
                Total
              </th>
            </tr>
          </thead>
          <tbody>
            {bars.map((b) => (
              <tr key={b.month} className="border-b border-gray-100 last:border-0">
                <th scope="row" className="py-1 text-left font-normal">
                  {monthName(b.month)}
                </th>
                <td className="py-1 text-right tabular-nums">{b.receiptCount}</td>
                <td className="py-1 text-right tabular-nums">
                  {formatMoney(String(b.value), currency)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </details>
    </div>
  );
}

function TrendTooltip({
  active,
  payload,
  currency,
}: {
  active?: boolean;
  payload?: { payload: TrendBar }[];
  currency: string;
}) {
  const b = payload?.[0]?.payload;
  if (!active || !b) return null;
  return (
    <div className="rounded-md border border-gray-200 bg-white px-3 py-2 text-xs shadow-md">
      <p className="font-medium text-gray-900">{monthName(b.month)}</p>
      <p className="mt-0.5 text-gray-700 tabular-nums">{formatMoney(String(b.value), currency)}</p>
      <p className="text-gray-500">
        {b.receiptCount} receipt{b.receiptCount === 1 ? "" : "s"}
      </p>
    </div>
  );
}
