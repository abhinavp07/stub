"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";

import { useMe } from "@/components/AppShell";
import { BudgetMeter } from "@/components/charts/BudgetMeter";
import { SpendingDonut } from "@/components/charts/SpendingDonut";
import { TrendChart } from "@/components/charts/TrendChart";
import { Skeleton } from "@/components/ui";
import { budgetsApi, exportCsvUrl, exportPdfUrl, insightsApi } from "@/lib/api";
import { monthLabel, monthName } from "@/lib/charts";
import { formatMoney } from "@/lib/format";
import type { InsightsSummary } from "@/lib/types";

function monthBounds(month: string): { from: string; to: string } {
  const [y, m] = month.split("-").map(Number);
  const last = new Date(y!, m!, 0).getDate();
  return { from: `${month}-01`, to: `${month}-${String(last).padStart(2, "0")}` };
}

export default function DashboardPage() {
  const { data: me } = useMe();
  const summary = useQuery({
    queryKey: ["insights", "summary"],
    queryFn: () => insightsApi.summary(),
  });
  const month = summary.data?.month;
  const byCategory = useQuery({
    queryKey: ["insights", "by-category", month],
    queryFn: () => insightsApi.byCategory(monthBounds(month!).from, monthBounds(month!).to),
    enabled: Boolean(month),
  });
  const trend = useQuery({ queryKey: ["insights", "trend"], queryFn: () => insightsApi.trend(12) });
  const budgets = useQuery({ queryKey: ["budgets"], queryFn: budgetsApi.list });
  const currency = summary.data?.currency ?? me?.currency ?? "USD";

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        {month && (
          <div className="flex flex-wrap gap-2">
            <a
              href={exportCsvUrl(monthBounds(month))}
              download
              className="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium hover:bg-gray-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
            >
              Export {monthName(month)} CSV
            </a>
            <a
              href={exportPdfUrl(monthBounds(month))}
              download
              className="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium hover:bg-gray-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
            >
              PDF report
            </a>
          </div>
        )}
      </div>

      {summary.isError ? (
        <ErrorCard message={summary.error.message} />
      ) : (
        <div className="grid gap-4 md:grid-cols-3">
          <Card className="md:col-span-2">
            {summary.data ? <Headline s={summary.data} /> : <Skeleton className="h-24 w-64" />}
          </Card>
          <Card>
            {summary.data ? (
              <NeedsReview count={summary.data.needs_review_count} />
            ) : (
              <Skeleton className="h-24 w-full" />
            )}
          </Card>
        </div>
      )}

      <div className="grid gap-4 lg:grid-cols-2">
        <Card title={month ? `Spending by category · ${monthName(month)}` : "Spending by category"}>
          {byCategory.data ? (
            <SpendingDonut
              items={byCategory.data.items}
              total={byCategory.data.total}
              currency={currency}
            />
          ) : byCategory.isError ? (
            <ErrorCard message={byCategory.error.message} />
          ) : (
            <Skeleton className="h-48 w-full" />
          )}
        </Card>
        <Card title="Monthly spending · last 12 months">
          {trend.data ? (
            <TrendChart points={trend.data.months} currency={currency} />
          ) : trend.isError ? (
            <ErrorCard message={trend.error.message} />
          ) : (
            <Skeleton className="h-56 w-full" />
          )}
        </Card>
      </div>

      <Card
        title="Budgets this month"
        action={
          <Link href="/budgets" className="text-sm text-blue-700 hover:underline">
            {budgets.data?.length ? "Edit budgets" : "Set budgets"}
          </Link>
        }
      >
        {budgets.data ? (
          budgets.data.length === 0 ? (
            <p className="py-4 text-sm text-gray-600">
              No budgets yet.{" "}
              <Link href="/budgets" className="font-medium text-blue-700 hover:underline">
                Set a monthly limit
              </Link>{" "}
              for a category to track your progress here.
            </p>
          ) : (
            <ul className="grid gap-5 md:grid-cols-2">
              {budgets.data.map((b) => (
                <li key={b.category_id}>
                  <BudgetMeter budget={b} currency={currency} />
                </li>
              ))}
            </ul>
          )
        ) : budgets.isError ? (
          <ErrorCard message={budgets.error.message} />
        ) : (
          <Skeleton className="h-16 w-full" />
        )}
      </Card>
    </div>
  );
}

function Headline({ s }: { s: InsightsSummary }) {
  const change = s.change_pct === null ? null : Number(s.change_pct);
  return (
    <div>
      <p className="text-sm text-gray-600">Spent in {monthName(s.month)}</p>
      {/* The one hero figure on the page. */}
      <p className="mt-1 text-5xl font-semibold tracking-tight">
        {formatMoney(s.total, s.currency)}
      </p>
      <p className="mt-2 text-sm text-gray-600">
        {s.receipt_count} receipt{s.receipt_count === 1 ? "" : "s"} ·{" "}
        {change === null ? (
          <>nothing recorded in {monthLabel(s.previous_month)}</>
        ) : (
          <>
            <span className="font-medium text-gray-900">
              <span aria-hidden>{change > 0 ? "↑" : change < 0 ? "↓" : "→"}</span>{" "}
              {Math.abs(change).toFixed(1)}% {change > 0 ? "more" : change < 0 ? "less" : "same"}
            </span>{" "}
            than {monthLabel(s.previous_month)} ({formatMoney(s.previous_total, s.currency)})
          </>
        )}
      </p>
    </div>
  );
}

function NeedsReview({ count }: { count: number }) {
  return (
    <div className="flex h-full flex-col justify-between gap-2">
      <p className="text-sm text-gray-600">Needs review</p>
      <p className="text-3xl font-semibold">{count}</p>
      {count > 0 ? (
        <Link
          href="/receipts?needs_review=true"
          className="text-sm font-medium text-blue-700 hover:underline"
        >
          Review {count === 1 ? "it" : "them"} →
        </Link>
      ) : (
        <p className="text-sm text-gray-500">All caught up.</p>
      )}
    </div>
  );
}

function Card({
  title,
  action,
  className = "",
  children,
}: {
  title?: string;
  action?: React.ReactNode;
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <section
      className={`rounded-lg border border-gray-200 bg-white p-4 sm:p-5 ${className}`}
      aria-label={title}
    >
      {(title || action) && (
        <div className="mb-4 flex items-center justify-between gap-3">
          {title && <h2 className="text-sm font-medium text-gray-900">{title}</h2>}
          {action}
        </div>
      )}
      {children}
    </section>
  );
}

function ErrorCard({ message }: { message: string }) {
  return (
    <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-800">
      Couldn&apos;t load this: {message}
    </p>
  );
}
