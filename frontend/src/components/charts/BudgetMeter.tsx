import { BUDGET_TONES, meterWidth } from "@/lib/charts";
import { formatMoney } from "@/lib/format";
import type { Budget } from "@/lib/types";

/** Budget progress: the fill carries the state (blue, then amber at the alert threshold, then
 *  red over 100%), always paired with an icon and a text label. */
export function BudgetMeter({
  budget: b,
  currency,
  showName = true,
}: {
  budget: Budget;
  currency: string;
  showName?: boolean;
}) {
  const tone = BUDGET_TONES[b.status];
  const width = meterWidth(b.percent_used);
  const over = Number(b.remaining) < 0;
  return (
    <div className="space-y-1.5">
      <div
        className={`flex items-baseline gap-3 text-sm ${showName ? "justify-between" : "justify-end"}`}
      >
        <span className={`min-w-0 items-center gap-2 ${showName ? "flex" : "hidden"}`}>
          <span
            aria-hidden
            className="h-2.5 w-2.5 shrink-0 rounded-sm"
            style={{ backgroundColor: b.color }}
          />
          <span className="truncate font-medium text-gray-900">{b.category_name}</span>
        </span>
        <span className="shrink-0 text-gray-600 tabular-nums">
          {formatMoney(b.spent, currency)} of {formatMoney(b.monthly_limit, currency)}
        </span>
      </div>
      <div
        role="meter"
        aria-label={`${b.category_name} budget`}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={Math.round(meterWidth(b.percent_used))}
        aria-valuetext={`${b.percent_used}% used, ${tone.label}`}
        className="h-2 overflow-hidden rounded-full"
        style={{ backgroundColor: tone.track }}
        data-status={b.status}
      >
        <div
          className="h-full rounded-full"
          style={{ width: `${width}%`, backgroundColor: tone.fill }}
        />
      </div>
      <p className={`flex justify-between gap-3 text-xs ${tone.text}`}>
        <span>
          <span aria-hidden>{tone.icon}</span> {tone.label} · {b.percent_used}%
        </span>
        <span className="text-gray-500 tabular-nums">
          {over
            ? `${formatMoney(String(-Number(b.remaining)), currency)} over`
            : `${formatMoney(b.remaining, currency)} left`}
        </span>
      </p>
    </div>
  );
}
