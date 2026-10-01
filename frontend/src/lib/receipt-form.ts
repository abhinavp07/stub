import { z } from "zod";

import type { ExtractedField, LineItemInput, ReceiptDetail, ReceiptUpdate } from "./types";

const MONEY_RE = /^-?\d{1,10}(\.\d{1,2})?$/;
const QTY_RE = /^\d{1,9}(\.\d{1,3})?$/;

/** "$1,234.5" -> "1234.5"; "" -> null. */
export function normalizeMoney(value: string): string | null {
  const v = value.replace(/[$,\s]/g, "");
  return v === "" ? null : v;
}

const money = z.string().refine((v) => {
  const n = normalizeMoney(v);
  return n === null || MONEY_RE.test(n);
}, "Enter an amount like 12.34");

const quantity = z
  .string()
  .refine((v) => v.trim() === "" || (QTY_RE.test(v.trim()) && Number(v) > 0), "Enter a number");

export const lineItemSchema = z.object({
  description: z.string().trim().min(1, "Add a description").max(500),
  quantity,
  unit_price: money,
  amount: money,
});

export const receiptFormSchema = z.object({
  merchant: z.string().max(200),
  purchase_date: z.string().refine((v) => v === "" || /^\d{4}-\d{2}-\d{2}$/.test(v), "Pick a date"),
  subtotal: money,
  tax: money,
  tip: money,
  total: money,
  line_items: z.array(lineItemSchema),
});

export type ReceiptFormValues = z.infer<typeof receiptFormSchema>;

export const SCALAR_FIELDS: ExtractedField[] = [
  "merchant",
  "purchase_date",
  "subtotal",
  "tax",
  "tip",
  "total",
];

export function toFormValues(r: ReceiptDetail): ReceiptFormValues {
  return {
    merchant: r.merchant ?? "",
    purchase_date: r.purchase_date ?? "",
    subtotal: r.subtotal ?? "",
    tax: r.tax ?? "",
    tip: r.tip ?? "",
    total: r.total ?? "",
    line_items: r.line_items.map((li) => ({
      description: li.description,
      quantity: li.quantity === null ? "" : String(Number(li.quantity)),
      unit_price: li.unit_price ?? "",
      amount: li.amount ?? "",
    })),
  };
}

/** Turn edited form values into API payloads. Only fields that differ from `initial` are sent,
 *  so the backend's user_edited_fields records exactly what the user changed. */
export function buildChanges(
  values: ReceiptFormValues,
  initial: ReceiptFormValues,
): { patch: ReceiptUpdate; lineItems: LineItemInput[] | null } {
  const patch: ReceiptUpdate = {};
  for (const name of SCALAR_FIELDS) {
    const raw = values[name].trim();
    if (raw === initial[name].trim()) continue;
    if (name === "merchant") patch.merchant = raw || null;
    else if (name === "purchase_date") patch.purchase_date = raw || null;
    else patch[name] = normalizeMoney(raw);
  }
  const items = values.line_items.map((li) => ({
    description: li.description.trim(),
    quantity: li.quantity.trim() || null,
    unit_price: normalizeMoney(li.unit_price),
    amount: normalizeMoney(li.amount),
  }));
  const initialItems = initial.line_items.map((li) => ({
    description: li.description.trim(),
    quantity: li.quantity.trim() || null,
    unit_price: normalizeMoney(li.unit_price),
    amount: normalizeMoney(li.amount),
  }));
  const lineItemsChanged = JSON.stringify(items) !== JSON.stringify(initialItems);
  return { patch, lineItems: lineItemsChanged ? items : null };
}
