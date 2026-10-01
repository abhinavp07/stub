import type { ReceiptStatus } from "@/lib/types";

const styles: Record<ReceiptStatus, [string, string]> = {
  pending_upload: ["Uploading", "bg-gray-100 text-gray-700"],
  processing: ["Processing", "bg-blue-100 text-blue-800"],
  ready: ["Ready", "bg-green-100 text-green-800"],
  failed: ["Failed", "bg-red-100 text-red-800"],
};

export function StatusBadge({ status }: { status: ReceiptStatus }) {
  const [label, cls] = styles[status];
  return (
    <span
      className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${cls}`}
    >
      {label}
    </span>
  );
}

export function NeedsReviewFlag() {
  return (
    <span className="inline-flex items-center rounded-full bg-amber-100 px-2 py-0.5 text-xs font-medium text-amber-800">
      Needs review
    </span>
  );
}
