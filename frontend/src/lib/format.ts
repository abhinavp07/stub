const moneyFormatters = new Map<string, Intl.NumberFormat>();

/** Format a decimal string (e.g. "12.30") as currency. Returns "—" for null. */
export function formatMoney(value: string | null | undefined, currency = "USD"): string {
  if (value === null || value === undefined || value === "") return "—";
  let fmt = moneyFormatters.get(currency);
  if (!fmt) {
    fmt = new Intl.NumberFormat(undefined, { style: "currency", currency });
    moneyFormatters.set(currency, fmt);
  }
  // Display only: Number is exact enough for formatting 2-decimal amounts under 10^12.
  return fmt.format(Number(value));
}

/** Format a YYYY-MM-DD date without shifting it through the local timezone. */
export function formatDate(value: string | null | undefined): string {
  if (!value) return "—";
  const [y, m, d] = value.split("-").map(Number);
  if (!y || !m || !d) return value;
  return new Date(y, m - 1, d).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
}

export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(0)} KB`;
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`;
}
