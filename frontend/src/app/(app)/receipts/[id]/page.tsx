"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useFieldArray, useForm, type UseFormRegister } from "react-hook-form";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { ReceiptImage } from "@/components/ReceiptImage";
import { NeedsReviewFlag, StatusBadge } from "@/components/StatusBadge";
import { useToast } from "@/components/Toast";
import { Button, Field, Input, Skeleton, Spinner, inputClass } from "@/components/ui";
import { ApiError, receiptsApi } from "@/lib/api";
import {
  buildChanges,
  receiptFormSchema,
  toFormValues,
  type ReceiptFormValues,
} from "@/lib/receipt-form";
import type { ExtractedField, ReceiptDetail } from "@/lib/types";

const FIELD_LABELS: Record<ExtractedField, string> = {
  merchant: "Merchant",
  purchase_date: "Date",
  subtotal: "Subtotal",
  tax: "Tax",
  tip: "Tip",
  total: "Total",
};

export default function ReceiptDetailPage() {
  const { id } = useParams<{ id: string }>();
  const query = useQuery({
    queryKey: ["receipts", "detail", id],
    queryFn: () => receiptsApi.get(id),
    // Poll every 2s while extraction runs; stops once it's ready or failed.
    refetchInterval: (q) => (q.state.data?.status === "processing" ? 2000 : false),
  });

  if (query.isPending) return <DetailSkeleton />;
  if (query.isError) {
    const notFound = query.error instanceof ApiError && query.error.status === 404;
    return (
      <div className="rounded-lg border border-gray-200 bg-white p-8 text-center">
        <h1 className="text-lg font-medium">
          {notFound ? "Receipt not found" : "Couldn't load this receipt"}
        </h1>
        <p className="mt-1 text-sm text-gray-600">
          {notFound ? "It may have been deleted." : query.error.message}
        </p>
        <Link href="/receipts" className="mt-4 inline-block text-sm text-blue-700 hover:underline">
          Back to receipts
        </Link>
      </div>
    );
  }
  return <ReceiptView receipt={query.data} />;
}

function ReceiptView({ receipt }: { receipt: ReceiptDetail }) {
  const router = useRouter();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [confirmDelete, setConfirmDelete] = useState(false);
  const processing = receipt.status === "processing";

  const form = useForm<ReceiptFormValues>({
    resolver: zodResolver(receiptFormSchema),
    defaultValues: toFormValues(receipt),
  });
  const {
    register,
    control,
    handleSubmit,
    reset,
    formState: { errors, isDirty },
  } = form;
  const lineItems = useFieldArray({ control, name: "line_items" });

  // Pick up fresh server data (e.g. processing finished), unless the user is mid-edit.
  useEffect(() => {
    if (!isDirty) reset(toFormValues(receipt));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [receipt.updated_at, receipt.status]);

  function onSaved(updated: ReceiptDetail) {
    queryClient.setQueryData(["receipts", "detail", updated.id], updated);
    void queryClient.invalidateQueries({ queryKey: ["receipts", "list"] });
    reset(toFormValues(updated));
  }

  const save = useMutation({
    mutationFn: async ({ values, confirm }: { values: ReceiptFormValues; confirm: boolean }) => {
      const { patch, lineItems: items } = buildChanges(values, toFormValues(receipt));
      let updated: ReceiptDetail | null = null;
      if (items) updated = await receiptsApi.replaceLineItems(receipt.id, items);
      if (confirm) patch.needs_review = false;
      if (Object.keys(patch).length > 0) updated = await receiptsApi.update(receipt.id, patch);
      return updated;
    },
    onSuccess: (updated, { confirm }) => {
      if (!updated) {
        toast.success("No changes to save");
        return;
      }
      onSaved(updated);
      toast.success(confirm ? "Receipt confirmed" : "Changes saved");
    },
    onError: (e) => toast.error(e.message),
  });

  const reprocess = useMutation({
    mutationFn: () => receiptsApi.reprocess(receipt.id),
    onSuccess: (updated) => {
      onSaved(updated);
      toast.success("Reprocessing… your edits will be kept");
    },
    onError: (e) => toast.error(e.message),
  });

  const remove = useMutation({
    mutationFn: () => receiptsApi.remove(receipt.id),
    onSuccess: () => {
      queryClient.removeQueries({ queryKey: ["receipts", "detail", receipt.id] });
      void queryClient.invalidateQueries({ queryKey: ["receipts", "list"] });
      toast.success("Receipt deleted");
      router.replace("/receipts");
    },
    onError: (e) => {
      setConfirmDelete(false);
      toast.error(e.message);
    },
  });

  const busy = save.isPending || reprocess.isPending || remove.isPending;
  const lowConfidence = new Set(receipt.low_confidence_fields);
  const title = receipt.merchant ?? receipt.original_filename;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-3">
        <Link
          href="/receipts"
          className="rounded text-sm text-gray-600 hover:text-gray-900 focus-visible:outline-2 focus-visible:outline-blue-600"
        >
          ← Receipts
        </Link>
        <h1 className="min-w-0 flex-1 truncate text-2xl font-semibold tracking-tight">{title}</h1>
        <div className="flex gap-2">
          {receipt.needs_review && receipt.status === "ready" && <NeedsReviewFlag />}
          <StatusBadge status={receipt.status} />
        </div>
      </div>

      {processing && (
        <div
          role="status"
          className="flex items-center gap-3 rounded-lg bg-blue-50 px-4 py-3 text-sm text-blue-900"
        >
          <Spinner /> Reading your receipt. This page updates automatically.
        </div>
      )}
      {receipt.status === "failed" && (
        <div
          role="alert"
          className="flex flex-wrap items-center gap-3 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-800"
        >
          <span className="flex-1">{receipt.error_message ?? "Extraction failed."}</span>
          <Button variant="secondary" onClick={() => reprocess.mutate()} disabled={busy}>
            Try again
          </Button>
        </div>
      )}

      <div className="grid gap-6 lg:grid-cols-2">
        <section aria-label="Original receipt">
          {receipt.image_url ? (
            <ReceiptImage url={receipt.image_url} contentType={receipt.content_type} alt={title} />
          ) : (
            <Skeleton className="h-96 w-full" />
          )}
        </section>

        <form
          aria-label="Receipt details"
          onSubmit={handleSubmit((values) => save.mutate({ values, confirm: false }))}
          className="space-y-6 rounded-lg border border-gray-200 bg-white p-4 sm:p-6"
        >
          <fieldset disabled={processing || busy} className="space-y-4">
            <legend className="sr-only">Receipt fields</legend>
            <ExtractedInput
              name="merchant"
              register={register}
              error={errors.merchant?.message}
              receipt={receipt}
              low={lowConfidence.has("merchant")}
            />
            <ExtractedInput
              name="purchase_date"
              type="date"
              register={register}
              error={errors.purchase_date?.message}
              receipt={receipt}
              low={lowConfidence.has("purchase_date")}
            />
            <div className="grid grid-cols-2 gap-4">
              {(["subtotal", "tax", "tip", "total"] as const).map((name) => (
                <ExtractedInput
                  key={name}
                  name={name}
                  money
                  register={register}
                  error={errors[name]?.message}
                  receipt={receipt}
                  low={lowConfidence.has(name)}
                />
              ))}
            </div>
          </fieldset>

          <fieldset disabled={processing || busy} className="space-y-3">
            <legend className="text-sm font-medium text-gray-700">Line items</legend>
            {lineItems.fields.length === 0 && (
              <p className="text-sm text-gray-500">No line items.</p>
            )}
            <ul className="space-y-3">
              {lineItems.fields.map((f, i) => {
                const e = errors.line_items?.[i];
                return (
                  <li
                    key={f.id}
                    className="grid grid-cols-[1fr_auto] gap-2 rounded-md border border-gray-200 p-2 sm:grid-cols-[1fr_4rem_5.5rem_5.5rem_auto]"
                  >
                    <div className="col-span-2 sm:col-span-1">
                      <label className="sr-only" htmlFor={`li-${i}-desc`}>
                        Item {i + 1} description
                      </label>
                      <input
                        id={`li-${i}-desc`}
                        placeholder="Description"
                        aria-invalid={e?.description ? true : undefined}
                        className={inputClass}
                        {...register(`line_items.${i}.description`)}
                      />
                      {e?.description && (
                        <p className="mt-1 text-xs text-red-600">{e.description.message}</p>
                      )}
                    </div>
                    <div className="col-span-2 grid grid-cols-3 gap-2 sm:contents">
                      {(
                        [
                          ["quantity", "Qty"],
                          ["unit_price", "Unit"],
                          ["amount", "Amount"],
                        ] as const
                      ).map(([key, label]) => (
                        <div key={key}>
                          <label className="sr-only" htmlFor={`li-${i}-${key}`}>
                            Item {i + 1} {label.toLowerCase()}
                          </label>
                          <input
                            id={`li-${i}-${key}`}
                            placeholder={label}
                            inputMode="decimal"
                            aria-invalid={e?.[key] ? true : undefined}
                            title={e?.[key]?.message}
                            className={`${inputClass} text-right tabular-nums`}
                            {...register(`line_items.${i}.${key}`)}
                          />
                        </div>
                      ))}
                    </div>
                    <Button
                      variant="ghost"
                      aria-label={`Remove item ${i + 1}`}
                      onClick={() => lineItems.remove(i)}
                      className="col-start-2 row-start-1 sm:col-start-auto sm:row-start-auto"
                    >
                      ✕
                    </Button>
                  </li>
                );
              })}
            </ul>
            <Button
              variant="secondary"
              onClick={() =>
                lineItems.append({ description: "", quantity: "", unit_price: "", amount: "" })
              }
            >
              Add line item
            </Button>
          </fieldset>

          <div className="flex flex-wrap gap-2 border-t border-gray-200 pt-4">
            <Button type="submit" disabled={processing || busy || !isDirty}>
              {save.isPending && !save.variables?.confirm && <Spinner />}
              Save changes
            </Button>
            {receipt.status === "ready" && (receipt.needs_review || isDirty) && (
              <Button
                variant="secondary"
                disabled={busy}
                onClick={handleSubmit((values) => save.mutate({ values, confirm: true }))}
              >
                {save.isPending && save.variables?.confirm && <Spinner />}
                {isDirty ? "Save & confirm" : "Confirm"}
              </Button>
            )}
            <Button
              variant="secondary"
              disabled={processing || busy || receipt.status === "pending_upload"}
              onClick={() => reprocess.mutate()}
              title="Run extraction again. Fields you've edited are kept."
            >
              {reprocess.isPending && <Spinner />}
              Reprocess
            </Button>
            {isDirty && (
              <Button variant="ghost" onClick={() => reset(toFormValues(receipt))} disabled={busy}>
                Discard
              </Button>
            )}
            <Button
              variant="danger"
              className="ml-auto"
              disabled={busy}
              onClick={() => setConfirmDelete(true)}
            >
              Delete
            </Button>
          </div>
        </form>
      </div>

      <ConfirmDialog
        open={confirmDelete}
        title="Delete this receipt?"
        body="The receipt and its uploaded file will be permanently deleted. This can't be undone."
        confirmLabel={remove.isPending ? "Deleting…" : "Delete"}
        busy={remove.isPending}
        onConfirm={() => remove.mutate()}
        onCancel={() => setConfirmDelete(false)}
      />
    </div>
  );
}

function ExtractedInput({
  name,
  register,
  error,
  receipt,
  low,
  money,
  type = "text",
}: {
  name: ExtractedField;
  register: UseFormRegister<ReceiptFormValues>;
  error?: string;
  receipt: ReceiptDetail;
  low: boolean;
  money?: boolean;
  type?: string;
}) {
  const confidence = receipt.field_confidence[name];
  const id = `field-${name}`;
  const lowNote =
    low && confidence !== undefined
      ? `Low confidence (${confidence.toFixed(0)}%). Please double-check.`
      : undefined;
  const describedBy = [error && `${id}-error`, lowNote && `${id}-confidence`]
    .filter(Boolean)
    .join(" ");
  return (
    <Field
      label={FIELD_LABELS[name]}
      htmlFor={id}
      error={error}
      hint={
        lowNote ? (
          <span id={`${id}-confidence`} className="text-amber-700">
            {lowNote}
          </span>
        ) : undefined
      }
    >
      <Input
        id={id}
        type={type}
        inputMode={money ? "decimal" : undefined}
        title={lowNote}
        aria-invalid={error ? true : undefined}
        aria-describedby={describedBy || undefined}
        className={`${money ? "text-right tabular-nums" : ""} ${
          low ? "border-amber-500 ring-2 ring-amber-300" : ""
        }`}
        {...register(name)}
      />
    </Field>
  );
}

function DetailSkeleton() {
  return (
    <div className="space-y-4" aria-busy="true" aria-label="Loading receipt">
      <Skeleton className="h-8 w-64" />
      <div className="grid gap-6 lg:grid-cols-2">
        <Skeleton className="h-96 w-full" />
        <div className="space-y-4 rounded-lg border border-gray-200 bg-white p-6">
          {Array.from({ length: 5 }, (_, i) => (
            <Skeleton key={i} className="h-10 w-full" />
          ))}
        </div>
      </div>
    </div>
  );
}
