"use client";

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { ConfirmDialog } from "@/components/ConfirmDialog";
import { useToast } from "@/components/Toast";
import { Button, Input, Skeleton } from "@/components/ui";
import { categoriesApi } from "@/lib/api";
import { useCategories, useDebounced } from "@/lib/hooks";
import type { Category, CategoryInput } from "@/lib/types";

// The validated categorical palette, in slot order.
const PALETTE = [
  "#2a78d6",
  "#eb6834",
  "#1baf7a",
  "#eda100",
  "#e87ba4",
  "#008300",
  "#4a3aa7",
  "#e34948",
];

export default function CategoriesPage() {
  const { data, isPending, isError, error, refetch } = useCategories();
  const queryClient = useQueryClient();
  const toast = useToast();
  const [toDelete, setToDelete] = useState<Category | null>(null);

  const invalidate = () => {
    void queryClient.invalidateQueries({ queryKey: ["categories"] });
    void queryClient.invalidateQueries({ queryKey: ["receipts"] });
  };

  const create = useMutation({
    mutationFn: categoriesApi.create,
    onSuccess: (c) => {
      invalidate();
      toast.success(`Added “${c.name}”`);
    },
    onError: (e) => toast.error(e.message),
  });
  const update = useMutation({
    mutationFn: ({ id, body }: { id: string; body: CategoryInput }) =>
      categoriesApi.update(id, body),
    onSuccess: () => {
      invalidate();
      toast.success("Category updated");
    },
    onError: (e) => toast.error(e.message),
  });
  const remove = useMutation({
    mutationFn: (c: Category) => categoriesApi.remove(c.id),
    onSuccess: (_, c) => {
      setToDelete(null);
      invalidate();
      toast.success(`Deleted “${c.name}”`);
    },
    onError: (e) => {
      setToDelete(null);
      toast.error(e.message);
    },
  });

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Categories</h1>
        <p className="mt-1 text-sm text-gray-600">
          Receipts are filed automatically by merchant. When you move a receipt to a different
          category, future receipts from that merchant follow.
        </p>
      </div>

      <NewCategoryForm
        busy={create.isPending}
        onCreate={(body) => create.mutateAsync(body).then(() => undefined)}
        nextColor={PALETTE[(data?.length ?? 0) % PALETTE.length]!}
      />

      {isPending ? (
        <div className="space-y-2">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      ) : isError ? (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-4 text-sm">
          <p className="text-red-800">Couldn&apos;t load categories: {error.message}</p>
          <Button variant="secondary" className="mt-2" onClick={() => void refetch()}>
            Try again
          </Button>
        </div>
      ) : data.length === 0 ? (
        <p className="rounded-lg border border-dashed border-gray-300 bg-white p-8 text-center text-sm text-gray-600">
          No categories yet. Add one above to start organizing receipts.
        </p>
      ) : (
        <ul className="divide-y divide-gray-200 rounded-lg border border-gray-200 bg-white">
          {data.map((c) => (
            <CategoryRow
              key={c.id}
              category={c}
              onSave={(body) => update.mutateAsync({ id: c.id, body }).then(() => undefined)}
              onDelete={() => setToDelete(c)}
            />
          ))}
        </ul>
      )}

      <ConfirmDialog
        open={toDelete !== null}
        title={`Delete “${toDelete?.name ?? ""}”?`}
        body={
          toDelete && toDelete.receipt_count > 0
            ? `${toDelete.receipt_count} receipt${toDelete.receipt_count === 1 ? "" : "s"} will become uncategorized. Any budget for this category is removed too.`
            : "Any budget for this category is removed too."
        }
        confirmLabel={remove.isPending ? "Deleting…" : "Delete"}
        busy={remove.isPending}
        onConfirm={() => toDelete && remove.mutate(toDelete)}
        onCancel={() => setToDelete(null)}
      />
    </div>
  );
}

function NewCategoryForm({
  onCreate,
  busy,
  nextColor,
}: {
  onCreate: (body: CategoryInput) => Promise<void>;
  busy: boolean;
  nextColor: string;
}) {
  const [name, setName] = useState("");
  const [color, setColor] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  return (
    <form
      onSubmit={async (e) => {
        e.preventDefault();
        const trimmed = name.trim();
        if (!trimmed) {
          setError("Enter a name");
          return;
        }
        setError(null);
        try {
          await onCreate({ name: trimmed, color: color ?? nextColor });
          setName("");
          setColor(null);
        } catch {
          // Toast already shown.
        }
      }}
      className="flex flex-wrap items-start gap-2 rounded-lg border border-gray-200 bg-white p-3"
    >
      <label htmlFor="new-category-color" className="sr-only">
        Color
      </label>
      <input
        id="new-category-color"
        type="color"
        value={color ?? nextColor}
        onChange={(e) => setColor(e.target.value)}
        className="h-10 w-10 shrink-0 cursor-pointer rounded-md border border-gray-300 bg-white p-1"
      />
      <div className="min-w-0 flex-1 basis-40">
        <label htmlFor="new-category-name" className="sr-only">
          New category name
        </label>
        <Input
          id="new-category-name"
          placeholder="New category name"
          maxLength={50}
          value={name}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? "new-category-error" : undefined}
          onChange={(e) => setName(e.target.value)}
        />
        {error && (
          <p id="new-category-error" className="mt-1 text-xs text-red-600">
            {error}
          </p>
        )}
      </div>
      <Button type="submit" disabled={busy}>
        Add category
      </Button>
    </form>
  );
}

function CategoryRow({
  category: c,
  onSave,
  onDelete,
}: {
  category: Category;
  onSave: (body: CategoryInput) => Promise<void>;
  onDelete: () => void;
}) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(c.name);
  const [color, setColor] = useState(c.color);
  const debouncedColor = useDebounced(color, 400);

  // Save once the user settles on a color, not on every step of dragging the picker.
  useEffect(() => {
    if (debouncedColor !== c.color) void onSave({ color: debouncedColor }).catch(() => {});
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedColor]);

  async function saveName() {
    const trimmed = name.trim();
    if (!trimmed || trimmed === c.name) {
      setName(c.name);
      setEditing(false);
      return;
    }
    try {
      await onSave({ name: trimmed });
      setEditing(false);
    } catch {
      setName(c.name);
    }
  }

  return (
    <li className="flex items-center gap-3 px-3 py-2.5">
      <label htmlFor={`color-${c.id}`} className="sr-only">
        Color for {c.name}
      </label>
      <input
        id={`color-${c.id}`}
        type="color"
        value={color}
        onChange={(e) => setColor(e.target.value)}
        className="h-8 w-8 shrink-0 cursor-pointer rounded-md border border-gray-300 bg-white p-0.5"
      />
      <div className="min-w-0 flex-1">
        {editing ? (
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void saveName();
            }}
            className="flex gap-2"
          >
            <label htmlFor={`name-${c.id}`} className="sr-only">
              Name
            </label>
            <Input
              id={`name-${c.id}`}
              value={name}
              maxLength={50}
              autoFocus
              onChange={(e) => setName(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Escape") {
                  setName(c.name);
                  setEditing(false);
                }
              }}
            />
            <Button type="submit" variant="secondary">
              Save
            </Button>
          </form>
        ) : (
          <>
            <p className="truncate font-medium">{c.name}</p>
            <p className="text-xs text-gray-500">
              {c.receipt_count} receipt{c.receipt_count === 1 ? "" : "s"}
            </p>
          </>
        )}
      </div>
      {!editing && (
        <div className="flex shrink-0 gap-1">
          <Button variant="ghost" onClick={() => setEditing(true)} aria-label={`Rename ${c.name}`}>
            Rename
          </Button>
          <Button variant="ghost" onClick={onDelete} aria-label={`Delete ${c.name}`}>
            Delete
          </Button>
        </div>
      )}
    </li>
  );
}
