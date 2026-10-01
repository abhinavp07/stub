"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useCallback, useRef, useState } from "react";

import { Button } from "@/components/ui";
import { formatBytes } from "@/lib/format";
import { ACCEPT, MAX_UPLOAD_MB, uploadReceipt, validateFile } from "@/lib/upload";

type UploadState =
  | { kind: "queued" }
  | { kind: "uploading"; progress: number }
  | { kind: "done"; receiptId: string }
  | { kind: "error"; message: string };

interface Upload {
  id: number;
  file: File;
  state: UploadState;
}

const CONCURRENCY = 3;

export default function UploadPage() {
  const queryClient = useQueryClient();
  const [uploads, setUploads] = useState<Upload[]>([]);
  const [dragging, setDragging] = useState(false);
  const nextId = useRef(0);
  const queue = useRef<Upload[]>([]);
  const active = useRef(0);
  const fileInput = useRef<HTMLInputElement>(null);
  const cameraInput = useRef<HTMLInputElement>(null);

  const update = useCallback((id: number, state: UploadState) => {
    setUploads((us) => us.map((u) => (u.id === id ? { ...u, state } : u)));
  }, []);

  // Each upload runs independently, so one failure never blocks the others.
  const pump = useCallback(() => {
    while (active.current < CONCURRENCY && queue.current.length > 0) {
      const job = queue.current.shift()!;
      active.current++;
      update(job.id, { kind: "uploading", progress: 0 });
      uploadReceipt(job.file, (progress) => update(job.id, { kind: "uploading", progress }))
        .then((receipt) => {
          update(job.id, { kind: "done", receiptId: receipt.id });
          void queryClient.invalidateQueries({ queryKey: ["receipts"] });
        })
        .catch((e: unknown) => {
          update(job.id, {
            kind: "error",
            message: e instanceof Error ? e.message : "Upload failed",
          });
        })
        .finally(() => {
          active.current--;
          pump();
        });
    }
  }, [queryClient, update]);

  const addFiles = useCallback(
    (files: FileList | File[]) => {
      const added: Upload[] = Array.from(files).map((file) => {
        const error = validateFile(file);
        return {
          id: nextId.current++,
          file,
          state: error ? { kind: "error", message: error } : { kind: "queued" },
        };
      });
      setUploads((us) => [...added, ...us]);
      queue.current.push(...added.filter((u) => u.state.kind === "queued"));
      pump();
    },
    [pump],
  );

  function onInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    if (e.target.files?.length) addFiles(e.target.files);
    e.target.value = ""; // allow picking the same file again
  }

  return (
    <div className="mx-auto max-w-2xl space-y-6">
      <h1 className="text-2xl font-semibold tracking-tight">Upload receipts</h1>

      <div
        onDragOver={(e) => {
          e.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault();
          setDragging(false);
          if (e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
        }}
        className={`flex flex-col items-center gap-4 rounded-lg border-2 border-dashed px-6 py-12 text-center transition-colors ${
          dragging ? "border-blue-500 bg-blue-50" : "border-gray-300 bg-white"
        }`}
      >
        <div>
          <p className="font-medium">Drag and drop receipts here</p>
          <p className="mt-1 text-sm text-gray-500">
            JPG, PNG or PDF, up to {MAX_UPLOAD_MB} MB each. Select as many as you like.
          </p>
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          <Button onClick={() => fileInput.current?.click()}>Choose files</Button>
          {/* On phones this opens the rear camera directly. */}
          <Button
            variant="secondary"
            className="sm:hidden"
            onClick={() => cameraInput.current?.click()}
          >
            Take photo
          </Button>
        </div>
        <input
          ref={fileInput}
          type="file"
          multiple
          accept={ACCEPT}
          onChange={onInputChange}
          className="sr-only"
          aria-label="Choose receipt files"
          tabIndex={-1}
        />
        <input
          ref={cameraInput}
          type="file"
          accept="image/*"
          capture="environment"
          onChange={onInputChange}
          className="sr-only"
          aria-label="Take a photo of a receipt"
          tabIndex={-1}
        />
      </div>

      {uploads.length > 0 && (
        <ul className="space-y-2" aria-label="Uploads">
          {uploads.map((u) => (
            <UploadRow key={u.id} upload={u} />
          ))}
        </ul>
      )}
    </div>
  );
}

function UploadRow({ upload: { file, state } }: { upload: Upload }) {
  const pct = state.kind === "uploading" ? Math.round(state.progress * 100) : 0;
  return (
    <li className="rounded-lg border border-gray-200 bg-white px-4 py-3">
      <div className="flex items-center gap-3">
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium">{file.name}</p>
          <p className="text-xs text-gray-500">{formatBytes(file.size)}</p>
        </div>
        <div className="shrink-0 text-sm">
          {state.kind === "queued" && <span className="text-gray-500">Waiting…</span>}
          {state.kind === "uploading" && (
            <span className="text-gray-700 tabular-nums">
              {pct < 100 ? `${pct}%` : "Finishing…"}
            </span>
          )}
          {state.kind === "done" && (
            <Link
              href={`/receipts/${state.receiptId}`}
              className="font-medium text-blue-700 underline-offset-2 hover:underline"
            >
              View receipt
            </Link>
          )}
          {state.kind === "error" && <span className="text-red-600">Failed</span>}
        </div>
      </div>
      {(state.kind === "uploading" || state.kind === "queued") && (
        <div
          role="progressbar"
          aria-label={`Uploading ${file.name}`}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={pct}
          className="mt-2 h-1.5 overflow-hidden rounded-full bg-gray-100"
        >
          <div className="h-full bg-blue-600 transition-[width]" style={{ width: `${pct}%` }} />
        </div>
      )}
      {state.kind === "error" && (
        <p role="alert" className="mt-1 text-sm text-red-600">
          {state.message}
        </p>
      )}
    </li>
  );
}
