"use client";

import { useState } from "react";

import { Button } from "@/components/ui";

const ZOOM_STEPS = [1, 1.5, 2, 3, 4];

export function ReceiptImage({
  url,
  contentType,
  alt,
}: {
  url: string;
  contentType: string;
  alt: string;
}) {
  const [step, setStep] = useState(0);
  const [failed, setFailed] = useState(false);
  const zoom = ZOOM_STEPS[step]!;

  if (contentType === "application/pdf") {
    return (
      <div className="flex h-[70vh] flex-col overflow-hidden rounded-lg border border-gray-200 bg-white">
        <iframe src={url} title={alt} className="h-full w-full flex-1" />
        <a
          href={url}
          target="_blank"
          rel="noreferrer"
          className="border-t border-gray-200 px-3 py-2 text-sm text-blue-700 hover:underline"
        >
          Open PDF in a new tab
        </a>
      </div>
    );
  }

  return (
    <div className="flex flex-col overflow-hidden rounded-lg border border-gray-200 bg-white">
      <div className="flex items-center gap-1 border-b border-gray-200 px-2 py-1.5">
        <Button
          variant="ghost"
          aria-label="Zoom out"
          disabled={step === 0}
          onClick={() => setStep((s) => Math.max(0, s - 1))}
        >
          −
        </Button>
        <span className="w-12 text-center text-xs text-gray-600 tabular-nums" aria-live="polite">
          {Math.round(zoom * 100)}%
        </span>
        <Button
          variant="ghost"
          aria-label="Zoom in"
          disabled={step === ZOOM_STEPS.length - 1}
          onClick={() => setStep((s) => Math.min(ZOOM_STEPS.length - 1, s + 1))}
        >
          +
        </Button>
        {step > 0 && (
          <Button variant="ghost" onClick={() => setStep(0)}>
            Fit
          </Button>
        )}
      </div>
      <div
        className="max-h-[70vh] overflow-auto bg-gray-100"
        tabIndex={0}
        aria-label="Receipt image"
      >
        {failed ? (
          <p className="p-6 text-sm text-gray-600">The image couldn&apos;t be loaded.</p>
        ) : (
          // Presigned/local URLs are dynamic and short-lived, so next/image optimization doesn't fit.
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={url}
            alt={alt}
            onError={() => setFailed(true)}
            style={{ width: `${zoom * 100}%`, maxWidth: "none" }}
            className="block h-auto"
          />
        )}
      </div>
    </div>
  );
}
