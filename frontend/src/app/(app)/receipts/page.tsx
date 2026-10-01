"use client";

import { useInfiniteQuery } from "@tanstack/react-query";
import Link from "next/link";
import { useEffect, useRef } from "react";

import { NeedsReviewFlag, StatusBadge } from "@/components/StatusBadge";
import { Button, Skeleton } from "@/components/ui";
import { receiptsApi } from "@/lib/api";
import { formatDate, formatMoney } from "@/lib/format";
import type { ReceiptSummary } from "@/lib/types";

export default function ReceiptsPage() {
  const query = useInfiniteQuery({
    queryKey: ["receipts", "list"],
    queryFn: ({ pageParam }) => receiptsApi.list({ cursor: pageParam, limit: 25 }),
    initialPageParam: null as string | null,
    getNextPageParam: (last) => last.next_cursor,
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
    const observer = new IntersectionObserver((entries) => {
      if (entries[0]?.isIntersecting && !isFetchingNextPage) void fetchNextPage();
    });
    observer.observe(el);
    return () => observer.disconnect();
  }, [hasNextPage, isFetchingNextPage, fetchNextPage]);

  const receipts = query.data?.pages.flatMap((p) => p.items) ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-2xl font-semibold tracking-tight">Receipts</h1>
        <Link
          href="/upload"
          className="rounded-md bg-gray-900 px-3 py-2 text-sm font-medium text-white hover:bg-gray-700 focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-blue-600"
        >
          Upload receipts
        </Link>
      </div>

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
        <EmptyState />
      ) : (
        <ul className="divide-y divide-gray-200 overflow-hidden rounded-lg border border-gray-200 bg-white">
          {receipts.map((r) => (
            <ReceiptRow key={r.id} receipt={r} />
          ))}
        </ul>
      )}

      <div ref={sentinel} />
      {isFetchingNextPage && <ListSkeleton rows={2} />}
    </div>
  );
}

function ReceiptRow({ receipt: r }: { receipt: ReceiptSummary }) {
  return (
    <li>
      <Link
        href={`/receipts/${r.id}`}
        className="flex items-center gap-4 px-4 py-3 hover:bg-gray-50 focus-visible:bg-gray-50 focus-visible:outline-2 focus-visible:-outline-offset-2 focus-visible:outline-blue-600"
      >
        <div className="min-w-0 flex-1">
          <p className="truncate font-medium">
            {r.merchant ?? <span className="text-gray-500">{r.original_filename}</span>}
          </p>
          <p className="text-sm text-gray-500">{formatDate(r.purchase_date)}</p>
        </div>
        <div className="flex shrink-0 flex-col items-end gap-1 sm:flex-row sm:items-center sm:gap-2">
          {r.needs_review && r.status === "ready" && <NeedsReviewFlag />}
          <StatusBadge status={r.status} />
        </div>
        <p className="w-24 shrink-0 text-right font-medium tabular-nums">
          {formatMoney(r.total, r.currency)}
        </p>
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
