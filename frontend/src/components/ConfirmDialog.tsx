"use client";

import { useEffect, useRef } from "react";

import { Button } from "@/components/ui";

export function ConfirmDialog({
  open,
  title,
  body,
  confirmLabel,
  onConfirm,
  onCancel,
  busy,
}: {
  open: boolean;
  title: string;
  body: string;
  confirmLabel: string;
  onConfirm: () => void;
  onCancel: () => void;
  busy?: boolean;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const d = ref.current;
    if (!d) return;
    if (open && !d.open) d.showModal();
    if (!open && d.open) d.close();
  }, [open]);

  return (
    <dialog
      ref={ref}
      onCancel={(e) => {
        e.preventDefault();
        onCancel();
      }}
      aria-labelledby="confirm-title"
      className="m-auto w-[min(24rem,calc(100vw-2rem))] rounded-lg p-0 shadow-xl backdrop:bg-black/40"
    >
      <div className="space-y-4 p-6">
        <h2 id="confirm-title" className="text-lg font-semibold">
          {title}
        </h2>
        <p className="text-sm text-gray-600">{body}</p>
        <div className="flex justify-end gap-2">
          <Button variant="secondary" onClick={onCancel} autoFocus>
            Cancel
          </Button>
          <Button variant="danger" onClick={onConfirm} disabled={busy}>
            {confirmLabel}
          </Button>
        </div>
      </div>
    </dialog>
  );
}
