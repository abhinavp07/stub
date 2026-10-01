"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { Suspense, useEffect, useMemo, useRef, useState } from "react";

import { CategoryChip } from "@/components/CategoryChip";
import { ReceiptFilterBar } from "@/components/ReceiptFilterBar";
import { NeedsReviewFlag, StatusBadge } from "@/components/StatusBadge";
import { Button, Skeleton } from "@/components/ui";
import { exportCsvUrl, exportPdfUrl, receiptsApi } from "@/lib/api";
import { activeFilterCount, filtersToParams, paramsToFilters } from "@/lib/filters";
import { formatDate, formatMoney } from "@/lib/format";
import { useCategoryMap } from "@/lib/hooks";
import type { Category, ReceiptFilters, ReceiptSummary } from "@/lib/types";

export default function ReceiptsPage() {
  return (
    <Suspense fallback={<ListSkeleton />}>
      <Receipts />
    </Suspense>
  );
}

function Receipts() {
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const filters = useMemo(() => paramsToFilters(searchParams), [searchParams]);
  const categories = useCategoryMap();

  function setFilters(next: ReceiptFilters) {
    const qs = filtersToParams(next).toString();
    router.replace(qs ? `${pathname}?${qs}` : pathname, { scroll: false });
  }

  const query = useInfiniteQuery({
    queryKey: ["receipts", "list", filters],
    queryFn: ({ pageParam }) => receiptsApi.list(filters, pageParam),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
    placeholderData: (prev) => prev,
    // Keep refreshing while anything is still processing.
    refetchInterval: (q) =>
      q.state.data?.pages.some((p) => p.items.some((r) => r.status === "processing"))
        ? 2000
        : false,
  });

  const sentinel = useRef<HTMLDivElement>(null);
  const { hasNextPage, isFetchingNextPage, fetchNextPage } = query;
  useEffect(() => {
    const el = sentinel.current;
    if (!el || !hasNextPage) return;
    const observer = new IntersectionObserver(
      (entries) => {
        if (entries[0]?.isIntersecting && !isFetchingNextPage) void fetchNextPage();
      },
      { rootMargin: "400px" },
    );
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const receipts = query.data?.pages.flatMap((p) => p.items) ?? [];
  const exportFilters = {
    from: filters.date_from,
    to: filters.date_to,
    category_id: filters.category_id,
  };
  const filtered = Boolean(filters.q) || activeFilterCount(filters) > 0;

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Receipts</h1>
        <div className="flex gap-2">
          <a
            href={exportCsvUrl(exportFilters)}
            download
            title="Exports receipts in the selected date range and category"
            className="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium hover:bg-gray-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
          >
            Export CSV
          </a>
          <a
            href={exportPdfUrl(exportFilters)}
            download
            title="A PDF report with totals and the receipt images, for the selected date range and category"
            className="rounded-md border border-gray-300 bg-white px-3 py-2 text-sm font-medium hover:bg-gray-50 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
          >
            PDF
          </a>
          <Link
            href="/upload"
            className="rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
          >
            Upload receipts
          </Link>
        </div>
      </div>

      <ReceiptFilterBar filters={filters} onChange={setFilters} />

      {query.isPending ? (
        <ListSkeleton />
      ) : query.isError ? (
        <div role="alert" className="rounded-lg border border-red-200 bg-red-50 p-6 text-sm">
          <p className="text-red-800">Couldn&apos;t load receipts: {query.error.message}</p>
          <Button variant="secondary" className="mt-3" onClick={() => void query.refetch()}>
            Try again
          </Button>
        </div>
      ) : receipts.length === 0 ? (
        filtered ? (
          <div className="rounded-lg border border-dashed border-gray-300 bg-white px-6 py-12 text-center">
            <h2 className="text-lg font-medium">No receipts match these filters</h2>
            <Button variant="secondary" className="mt-4" onClick={() => setFilters({})}>
              Clear search and filters
            </Button>
          </div>
        ) : (
          <EmptyState />
        )
      ) : (
        <ul
          className={`divide-y divide-gray-200 overflow-hidden rounded-lg border border-gray-200 bg-white transition-opacity ${
            query.isPlaceholderData ? "opacity-60" : ""
          }`}
          aria-busy={query.isPlaceholderData}
        >
          {receipts.map((r) => (
            <ReceiptRow
              key={r.id}
              receipt={r}
              category={r.category_id ? categories.get(r.category_id) : undefined}
            />
          ))}
        </ul>
      )}

      <div ref={sentinel} />
      {isFetchingNextPage && <ListSkeleton rows={2} />}
    </div>
  );
}

function Thumbnail({ receipt }: { receipt: ReceiptSummary }) {
  const [failed, setFailed] = useState(false);
  if (receipt.thumbnail_url && !failed) {
    return (
      // Dynamic, short-lived URLs: next/image optimization doesn't apply.
      // eslint-disable-next-line @next/next/no-img-element
      <img
        src={receipt.thumbnail_url}
        alt=""
        loading="lazy"
        onError={() => setFailed(true)}
        className="h-12 w-12 shrink-0 rounded-md border border-gray-200 bg-gray-100 object-cover"
      />
    );
  }
  return (
    <div
      aria-hidden
      className="flex h-12 w-12 shrink-0 items-center justify-center rounded-md border border-gray-200 bg-gray-50 text-[10px] font-semibold text-gray-500"
    >
      {receipt.content_type === "application/pdf" ? "PDF" : "IMG"}
    </div>
  );
}

function ReceiptRow({
  receipt: r,
  category,
}: {
  receipt: ReceiptSummary;
  category: Category | undefined;
}) {
  return (
    <li>
      <Link
        href={`/receipts/${r.id}`}
        className="flex items-center gap-3 px-3 py-3 hover:bg-gray-50 focus-visible:bg-gray-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-blue-600 sm:gap-4 sm:px-4"
      >
        <Thumbnail receipt={r} />
        <div className="min-w-0 flex-1 space-y-1">
          <p className="truncate font-medium">
            {r.merchant ?? <span className="text-gray-500">{r.original_filename}</span>}
          </p>
          <div className="flex flex-wrap items-center gap-x-2 gap-y-1 text-sm text-gray-500">
            <span>{formatDate(r.purchase_date)}</span>
            {r.status === "ready" && <CategoryChip category={category} />}
          </div>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1">
          <p className="font-medium tabular-nums">{formatMoney(r.total, r.currency)}</p>
          <div className="flex flex-wrap justify-end gap-1">
            {r.needs_review && r.status === "ready" && <NeedsReviewFlag />}
            {r.status !== "ready" && <StatusBadge status={r.status} />}
          </div>
        </div>
      </Link>
    </li>
  );
}

function ListSkeleton({ rows = 5 }: { rows?: number }) {
  return (
    <div
      className="space-y-px overflow-hidden rounded-lg border border-gray-200 bg-white"
      aria-busy="true"
      aria-label="Loading receipts"
    >
      {Array.from({ length: rows }, (_, i) => (
        <div key={i} className="flex items-center gap-4 px-4 py-4">
          <Skeleton className="h-12 w-12" />
          <div className="flex-1 space-y-2">
            <Skeleton className="h-4 w-40" />
            <Skeleton className="h-3 w-24" />
          </div>
          <Skeleton className="h-4 w-16" />
        </div>
      ))}
    </div>
  );
}

function EmptyState() {
  return (
    <div className="rounded-lg border border-dashed border-gray-300 bg-white px-6 py-12 text-center">
      <h2 className="text-lg font-medium">No receipts yet</h2>
      <p className="mt-1 text-sm text-gray-600">
        Upload a photo or PDF and we&apos;ll pull out the details for you.
      </p>
      <Link
        href="/upload"
        className="mt-4 inline-block rounded-md bg-gray-900 px-4 py-2 text-sm font-medium text-white hover:bg-gray-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
      >
        Upload your first receipt
      </Link>
    </div>
  );
}
