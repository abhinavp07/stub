"use client";

import { useEffect, useState } from "react";

import { Button, inputClass } from "@/components/ui";
import { activeFilterCount } from "@/lib/filters";
import { useCategories, useDebounced } from "@/lib/hooks";
import type { ReceiptFilters } from "@/lib/types";

const selectClass = `${inputClass} pr-8`;

export function ReceiptFilterBar({
  filters,
  onChange,
}: {
  filters: ReceiptFilters;
  onChange: (next: ReceiptFilters) => void;
}) {
  const { data: categories } = useCategories();
  const [search, setSearch] = useState(filters.q ?? "");
  const debouncedSearch = useDebounced(search);
  const count = activeFilterCount(filters);
  const [open, setOpen] = useState(count > 0);

  // Push the debounced search term into the URL.
  useEffect(() => {
    if ((filters.q ?? "") !== debouncedSearch)
      onChange({ ...filters, q: debouncedSearch || undefined });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [debouncedSearch]);

  // Keep the box in sync when filters change elsewhere (e.g. "Clear all", back button).
  useEffect(() => {
    setSearch(filters.q ?? "");
  }, [filters.q]);

  function set<K extends keyof ReceiptFilters>(key: K, value: ReceiptFilters[K] | "") {
    onChange({ ...filters, [key]: value === "" ? undefined : value });
  }

  return (
    <div className="space-y-3 rounded-lg border border-gray-200 bg-white p-3">
      <div className="flex flex-wrap gap-2">
        <div className="min-w-0 flex-1 basis-48">
          <label htmlFor="receipt-search" className="sr-only">
            Search merchants
          </label>
          <input
            id="receipt-search"
            type="search"
            placeholder="Search merchants…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className={inputClass}
          />
        </div>
        <div>
          <label htmlFor="receipt-sort" className="sr-only">
            Sort by
          </label>
          <select
            id="receipt-sort"
            value={filters.sort ?? "purchase_date"}
            onChange={(e) => set("sort", e.target.value as ReceiptFilters["sort"])}
            className={selectClass}
          >
            <option value="purchase_date">Newest first</option>
            <option value="total">Highest total</option>
          </select>
        </div>
        <Button
          variant="secondary"
          aria-expanded={open}
          aria-controls="receipt-filters"
          onClick={() => setOpen((o) => !o)}
        >
          Filters{count > 0 && ` (${count})`}
        </Button>
      </div>

      {open && (
        <div
          id="receipt-filters"
          className="grid grid-cols-2 gap-3 border-t border-gray-100 pt-3 sm:grid-cols-4"
        >
          <FilterField label="Category" id="f-category">
            <select
              id="f-category"
              value={filters.category_id ?? ""}
              onChange={(e) => set("category_id", e.target.value)}
              className={selectClass}
            >
              <option value="">All</option>
              <option value="none">Uncategorized</option>
              {categories?.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name}
                </option>
              ))}
            </select>
          </FilterField>
          <FilterField label="Status" id="f-status">
            <select
              id="f-status"
              value={filters.status ?? ""}
              onChange={(e) => set("status", e.target.value as ReceiptFilters["status"])}
              className={selectClass}
            >
              <option value="">Any</option>
              <option value="ready">Ready</option>
              <option value="processing">Processing</option>
              <option value="failed">Failed</option>
            </select>
          </FilterField>
          <FilterField label="From" id="f-from">
            <input
              id="f-from"
              type="date"
              value={filters.date_from ?? ""}
              onChange={(e) => set("date_from", e.target.value)}
              className={inputClass}
            />
          </FilterField>
          <FilterField label="To" id="f-to">
            <input
              id="f-to"
              type="date"
              value={filters.date_to ?? ""}
              onChange={(e) => set("date_to", e.target.value)}
              className={inputClass}
            />
          </FilterField>
          <FilterField label="Min total" id="f-min">
            <AmountInput
              id="f-min"
              value={filters.min_total}
              onCommit={(v) => set("min_total", v)}
            />
          </FilterField>
          <FilterField label="Max total" id="f-max">
            <AmountInput
              id="f-max"
              value={filters.max_total}
              onCommit={(v) => set("max_total", v)}
            />
          </FilterField>
          <FilterField label="Tag" id="f-tag">
            <TextCommitInput id="f-tag" value={filters.tag} onCommit={(v) => set("tag", v)} />
          </FilterField>
          <div className="flex items-end">
            <label className="flex items-center gap-2 py-2 text-sm">
              <input
                type="checkbox"
                checked={filters.needs_review === true}
                onChange={(e) => set("needs_review", e.target.checked ? true : "")}
                className="h-4 w-4 rounded border-gray-300"
              />
              Needs review only
            </label>
          </div>
          {count > 0 && (
            <div className="col-span-2 sm:col-span-4">
              <Button
                variant="ghost"
                onClick={() => onChange({ q: filters.q, sort: filters.sort })}
              >
                Clear filters
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}

function FilterField({
  label,
  id,
  children,
}: {
  label: string;
  id: string;
  children: React.ReactNode;
}) {
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="block text-xs font-medium text-gray-600">
        {label}
      </label>
      {children}
    </div>
  );
}

/** Text input that only updates the filter on blur or Enter, so typing doesn't refetch. */
function TextCommitInput({
  id,
  value,
  onCommit,
  inputMode,
  pattern,
}: {
  id: string;
  value: string | undefined;
  onCommit: (v: string) => void;
  inputMode?: "decimal";
  pattern?: RegExp;
}) {
  const [draft, setDraft] = useState(value ?? "");
  useEffect(() => setDraft(value ?? ""), [value]);
  const commit = () => {
    const v = draft.trim();
    if (pattern && v && !pattern.test(v)) {
      setDraft(value ?? "");
      return;
    }
    if (v !== (value ?? "")) onCommit(v);
  };
  return (
    <input
      id={id}
      value={draft}
      inputMode={inputMode}
      onChange={(e) => setDraft(e.target.value)}
      onBlur={commit}
      onKeyDown={(e) => e.key === "Enter" && commit()}
      className={inputClass}
    />
  );
}

function AmountInput(props: {
  id: string;
  value: string | undefined;
  onCommit: (v: string) => void;
}) {
  return <TextCommitInput {...props} inputMode="decimal" pattern={/^\d+(\.\d{1,2})?$/} />;
}
