"use client";

import { useQuery } from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { categoriesApi } from "./api";
import type { Category } from "./types";

export function useCategories() {
  return useQuery({ queryKey: ["categories"], queryFn: categoriesApi.list, staleTime: 60_000 });
}

export function useCategoryMap(): Map<string, Category> {
  const { data } = useCategories();
  return new Map((data ?? []).map((c) => [c.id, c]));
}

export function useDebounced<T>(value: T, ms = 300): T {
  const [debounced, setDebounced] = useState(value);
  useEffect(() => {
    const t = setTimeout(() => setDebounced(value), ms);
    return () => clearTimeout(t);
  }, [value, ms]);
  return debounced;
}
