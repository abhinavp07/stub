import type { Category } from "@/lib/types";

export function CategoryChip({ category }: { category: Category | undefined }) {
  if (!category) {
    return (
      <span className="inline-flex items-center rounded-full border border-dashed border-gray-300 px-2 py-0.5 text-xs text-gray-500">
        Uncategorized
      </span>
    );
  }
  return (
    <span className="inline-flex max-w-[10rem] items-center gap-1.5 rounded-full bg-gray-100 px-2 py-0.5 text-xs font-medium text-gray-800">
      <span
        aria-hidden
        className="h-2 w-2 shrink-0 rounded-full"
        style={{ backgroundColor: category.color }}
      />
      <span className="truncate">{category.name}</span>
    </span>
  );
}
