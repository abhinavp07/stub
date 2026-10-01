import { describe, expect, it } from "vitest";

import { buildChanges, receiptFormSchema, toFormValues } from "@/lib/receipt-form";
import type { ReceiptDetail } from "@/lib/types";

const receipt: ReceiptDetail = {
  id: "r1",
  status: "ready",
  error_message: null,
  original_filename: "r.jpg",
  content_type: "image/jpeg",
  merchant: "Kroger",
  purchase_date: "2024-03-15",
  subtotal: "23.47",
  tax: "1.64",
  tip: null,
  total: "25.11",
  currency: "USD",
  category_id: null,
  tags: [],
  needs_review: false,
  created_at: "2024-03-15T00:00:00Z",
  updated_at: "2024-03-15T00:00:00Z",
  notes: null,
  field_confidence: { merchant: 99 },
  user_edited_fields: [],
  low_confidence_fields: [],
  image_url: null,
  thumbnail_url: null,
  line_items: [
    {
      id: "l1",
      position: 0,
      description: "Bananas",
      quantity: "2.000",
      unit_price: null,
      amount: "1.29",
    },
  ],
};

describe("buildChanges", () => {
  it("sends nothing when nothing changed", () => {
    const initial = toFormValues(receipt);
    expect(buildChanges(structuredClone(initial), initial)).toEqual({
      patch: {},
      lineItems: null,
    });
  });

  it("sends only changed scalar fields, normalizing money and blanks", () => {
    const initial = toFormValues(receipt);
    const values = { ...initial, merchant: "  Kroger #12 ", total: "$1,025.10", tip: "", tax: "" };
    expect(buildChanges(values, initial).patch).toEqual({
      merchant: "Kroger #12",
      total: "1025.10",
      tax: null,
    });
  });

  it("sends the whole line item list when any item changes", () => {
    const initial = toFormValues(receipt);
    expect(initial.line_items[0]!.quantity).toBe("2");
    const values = {
      ...initial,
      line_items: [
        ...initial.line_items,
        { description: " Milk ", quantity: "", unit_price: "", amount: "3.49" },
      ],
    };
    expect(buildChanges(values, initial).lineItems).toEqual([
      { description: "Bananas", quantity: "2", unit_price: null, amount: "1.29" },
      { description: "Milk", quantity: null, unit_price: null, amount: "3.49" },
    ]);
  });

  it("detects removing every line item", () => {
    const initial = toFormValues(receipt);
    expect(buildChanges({ ...initial, line_items: [] }, initial).lineItems).toEqual([]);
  });
});

describe("buildChanges for organizing fields", () => {
  it("sends category, notes and tags only when changed", () => {
    const initial = toFormValues({ ...receipt, tags: ["work"], notes: "hi" });
    expect(buildChanges(structuredClone(initial), initial).patch).toEqual({});
    const values = { ...initial, category_id: "c1", notes: "  ", tags: ["work", "tax"] };
    expect(buildChanges(values, initial).patch).toEqual({
      category_id: "c1",
      notes: null,
      tags: ["work", "tax"],
    });
  });

  it("clears the category with null", () => {
    const initial = toFormValues({ ...receipt, category_id: "c1" });
    expect(buildChanges({ ...initial, category_id: "" }, initial).patch).toEqual({
      category_id: null,
    });
  });
});

describe("receiptFormSchema", () => {
  it("rejects malformed money and accepts common formats", () => {
    const base = toFormValues(receipt);
    expect(receiptFormSchema.safeParse({ ...base, total: "12.345" }).success).toBe(false);
    expect(receiptFormSchema.safeParse({ ...base, total: "abc" }).success).toBe(false);
    expect(receiptFormSchema.safeParse({ ...base, total: "$1,234.50" }).success).toBe(true);
    expect(receiptFormSchema.safeParse({ ...base, total: "-5" }).success).toBe(true);
  });

  it("requires line item descriptions", () => {
    const base = toFormValues(receipt);
    const bad = {
      ...base,
      line_items: [{ description: " ", quantity: "", unit_price: "", amount: "" }],
    };
    expect(receiptFormSchema.safeParse(bad).success).toBe(false);
  });
});
