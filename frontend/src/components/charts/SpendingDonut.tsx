"use client";

import { Cell, Pie, PieChart, ResponsiveContainer, Tooltip } from "recharts";

import { donutSegments, type DonutSegment } from "@/lib/charts";
import { formatMoney } from "@/lib/format";
import type { CategoryTotal } from "@/lib/types";

const pct = (share: number) => `${Math.round(share * 100)}%`;

/** Spending by category as a donut plus a legend table. The legend always names every segment
 *  with its amount, so identity never depends on color alone. */
export function SpendingDonut({
  items,
  total,
  currency,
}: {
  items: CategoryTotal[];
  total: string;
  currency: string;
}) {
  const segments = donutSegments(items);
  if (segments.length === 0) {
    return (
      <p className="flex h-48 items-center justify-center text-sm text-gray-500">
        No spending recorded this month yet.
      </p>
    );
  }

  return (
    <div className="flex flex-col items-center gap-6 sm:flex-row sm:items-center">
      <div
        className="relative h-44 w-44 shrink-0"
        role="img"
        aria-label={`Spending by category: ${segments.map((s) => `${s.name} ${pct(s.share)}`).join(", ")}`}
      >
        <ResponsiveContainer
          width="100%"
          height="100%"
          initialDimension={{ width: 176, height: 176 }}
        >
          <PieChart>
            <Pie
              data={segments}
              dataKey="value"
              nameKey="name"
              innerRadius="62%"
              outerRadius="100%"
              startAngle={90}
              endAngle={-270}
              cornerRadius={4}
              // 2px surface gap between segments (none for a full ring, which would show a seam).
              stroke={segments.length > 1 ? "#ffffff" : "none"}
              strokeWidth={2}
              isAnimationActive={false}
            >
              {segments.map((s) => (
                <Cell key={s.key} fill={s.color} />
              ))}
            </Pie>
            <Tooltip content={<DonutTooltip currency={currency} />} />
          </PieChart>
        </ResponsiveContainer>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          <span className="text-xs text-gray-500">Total</span>
          <span className="text-sm font-semibold">{formatMoney(total, currency)}</span>
        </div>
      </div>

      <table className="w-full text-sm">
        <caption className="sr-only">Spending by category</caption>
        <thead className="sr-only">
          <tr>
            <th scope="col">Category</th>
            <th scope="col">Amount</th>
            <th scope="col">Share</th>
          </tr>
        </thead>
        <tbody>
          {segments.map((s) => (
            <tr key={s.key} className="border-b border-gray-100 last:border-0">
              <th scope="row" className="py-1.5 pr-2 text-left font-normal">
                <span className="flex items-center gap-2">
                  <span
                    aria-hidden
                    className="h-2.5 w-2.5 shrink-0 rounded-sm"
                    style={{ backgroundColor: s.color }}
                  />
                  <span className="truncate text-gray-800">{s.name}</span>
                </span>
              </th>
              <td className="py-1.5 text-right text-gray-900 tabular-nums">
                {formatMoney(String(s.value), currency)}
              </td>
              <td className="w-12 py-1.5 text-right text-gray-500 tabular-nums">{pct(s.share)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function DonutTooltip({
  active,
  payload,
  currency,
}: {
  active?: boolean;
  payload?: { payload: DonutSegment }[];
  currency: string;
}) {
  const s = payload?.[0]?.payload;
  if (!active || !s) return null;
  return (
    <div className="rounded-md border border-gray-200 bg-white px-3 py-2 text-xs shadow-md">
      <p className="flex items-center gap-1.5 font-medium text-gray-900">
        <span aria-hidden className="h-2 w-2 rounded-sm" style={{ backgroundColor: s.color }} />
        {s.name}
      </p>
      <p className="mt-0.5 text-gray-700 tabular-nums">
        {formatMoney(String(s.value), currency)} · {pct(s.share)}
      </p>
      <p className="text-gray-500">
        {s.receiptCount} receipt{s.receiptCount === 1 ? "" : "s"}
      </p>
    </div>
  );
}
