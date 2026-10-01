"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useState } from "react";

import { useMe } from "@/components/AppShell";
import { BudgetMeter } from "@/components/charts/BudgetMeter";
import { useToast } from "@/components/Toast";
import { Button, Skeleton, inputClass } from "@/components/ui";
import { budgetsApi } from "@/lib/api";
import { useCategories } from "@/lib/hooks";
import { normalizeMoney } from "@/lib/receipt-form";
import type { Budget, Category } from "@/lib/types";

const LIMIT_RE = /^\d{1,10}(\.\d{1,2})?$/;

export default function BudgetsPage() {
  const categories = useCategories();
  const budgets = useQuery({ queryKey: ["budgets"], queryFn: budgetsApi.list });
  const { data: me } = useMe();
  const currency = me?.currency ?? "USD";
  const byCategory = new Map((budgets.data ?? []).map((b) => [b.category_id, b]));

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Budgets</h1>
        <p className="mt-1 text-sm text-gray-600">
          Set a monthly limit for any category. Bars turn amber at your alert threshold and red once
          you go over.
        </p>
      </div>

      {categories.isPending || budgets.isPending ? (
        <div className="space-y-2">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-20 w-full" />
          ))}
        </div>
      ) : categories.isError || budgets.isError ? (
        <p role="alert" className="rounded-md bg-red-50 p-3 text-sm text-red-800">
          Couldn&apos;t load budgets. Refresh to try again.
        </p>
      ) : (
        <ul className="divide-y divide-gray-200 rounded-lg border border-gray-200 bg-white">
          {categories.data.map((c) => (
            <BudgetRow
              key={`${c.id}-${byCategory.get(c.id)?.monthly_limit ?? ""}`}
              category={c}
              budget={byCategory.get(c.id)}
              currency={currency}
            />
          ))}
        </ul>
      )}
    </div>
  );
}

function BudgetRow({
  category: c,
  budget,
  currency,
}: {
  category: Category;
  budget: Budget | undefined;
  currency: string;
}) {
  const queryClient = useQueryClient();
  const toast = useToast();
  const [limit, setLimit] = useState(budget?.monthly_limit ?? "");
  const [threshold, setThreshold] = useState(String(budget?.alert_threshold_pct ?? 80));
  const [error, setError] = useState<string | null>(null);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["budgets"] });
  };
  const save = useMutation({
    mutationFn: () =>
      budgetsApi.set(c.id, {
        monthly_limit: normalizeMoney(limit)!,
        alert_threshold_pct: Number(threshold),
      }),
    onSuccess: () => {
      invalidate();
      toast.success(`Saved ${c.name} budget`);
    },
    onError: (e) => toast.error(e.message),
  });
  const remove = useMutation({
    mutationFn: () => budgetsApi.remove(c.id),
    onSuccess: () => {
      invalidate();
      toast.success(`Removed ${c.name} budget`);
    },
    onError: (e) => toast.error(e.message),
  });

  function submit(e: React.FormEvent) {
    e.preventDefault();
    const normalized = normalizeMoney(limit);
    if (!normalized || !LIMIT_RE.test(normalized) || Number(normalized) <= 0) {
      setError("Enter a monthly limit like 250 or 99.50");
      return;
    }
    const t = Number(threshold);
    if (!Number.isInteger(t) || t < 1 || t > 100) {
      setError("Alert threshold must be between 1 and 100%");
      return;
    }
    setError(null);
    save.mutate();
  }

  const dirty =
    (normalizeMoney(limit) ?? "") !== (budget ? normalizeMoney(budget.monthly_limit) : "") ||
    threshold !== String(budget?.alert_threshold_pct ?? 80);
  const ids = { limit: `limit-${c.id}`, threshold: `threshold-${c.id}`, error: `err-${c.id}` };

  return (
    <li className="space-y-3 px-4 py-4">
      <form onSubmit={submit} className="flex flex-wrap items-end gap-3" noValidate>
        <div className="flex min-w-0 flex-1 basis-40 items-center gap-2 self-center">
          <span
            aria-hidden
            className="h-3 w-3 shrink-0 rounded-sm"
            style={{ backgroundColor: c.color }}
          />
          <span className="truncate font-medium">{c.name}</span>
        </div>
        <div className="w-32">
          <label htmlFor={ids.limit} className="block text-xs font-medium text-gray-600">
            Monthly limit ({currency})
          </label>
          <input
            id={ids.limit}
            inputMode="decimal"
            placeholder="No budget"
            value={limit}
            onChange={(e) => setLimit(e.target.value)}
            aria-invalid={error ? true : undefined}
            aria-describedby={error ? ids.error : undefined}
            className={`${inputClass} text-right tabular-nums`}
          />
        </div>
        <div className="w-24">
          <label htmlFor={ids.threshold} className="block text-xs font-medium text-gray-600">
            Alert at (%)
          </label>
          <input
            id={ids.threshold}
            type="number"
            min={1}
            max={100}
            value={threshold}
            onChange={(e) => setThreshold(e.target.value)}
            className={`${inputClass} text-right tabular-nums`}
          />
        </div>
        <div className="flex gap-2">
          <Button type="submit" disabled={save.isPending || !dirty || limit.trim() === ""}>
            Save
          </Button>
          {budget && (
            <Button variant="ghost" onClick={() => remove.mutate()} disabled={remove.isPending}>
              Remove
            </Button>
          )}
        </div>
      </form>
      {error && (
        <p id={ids.error} className="text-xs text-red-600">
          {error}
        </p>
      )}
      {budget && <BudgetMeter budget={budget} currency={currency} showName={false} />}
    </li>
  );
}
