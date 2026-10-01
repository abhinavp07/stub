import { receiptsApi } from "./api";
import type { ReceiptDetail } from "./types";

// Mirrors the backend's ALLOWED_CONTENT_TYPES and MAX_UPLOAD_MB.
export const ALLOWED_TYPES: Record<string, string> = {
  "image/jpeg": "JPG",
  "image/png": "PNG",
  "application/pdf": "PDF",
};
export const MAX_UPLOAD_MB = 10;
export const MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024;
export const ACCEPT = "image/jpeg,image/png,application/pdf,.jpg,.jpeg,.png,.pdf";

/** Returns an error message, or null if the file can be uploaded. */
export function validateFile(file: Pick<File, "type" | "size">): string | null {
  if (!(file.type in ALLOWED_TYPES)) return "Only JPG, PNG and PDF files are supported";
  if (file.size === 0) return "File is empty";
  if (file.size > MAX_UPLOAD_BYTES) return `Files must be ${MAX_UPLOAD_MB} MB or smaller`;
  return null;
}

/** POST a file to a presigned URL (S3 or the local stand-in) as multipart form data,
 *  reporting progress as a 0-1 fraction. */
export function postFile(
  url: string,
  fields: Record<string, string>,
  file: File,
  onProgress: (fraction: number) => void,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const form = new FormData();
    for (const [k, v] of Object.entries(fields)) form.append(k, v);
    form.append("file", file); // S3 requires the file to be the last field

    const xhr = new XMLHttpRequest();
    xhr.open("POST", url);
    xhr.upload.onprogress = (e) => {
      if (e.lengthComputable) onProgress(e.loaded / e.total);
    };
    xhr.onload = () => {
      if (xhr.status >= 200 && xhr.status < 300) {
        onProgress(1);
        resolve();
      } else {
        reject(new Error(xhr.status === 413 ? "File is too large" : "Upload failed"));
      }
    };
    xhr.onerror = () => reject(new Error("Network error during upload"));
    xhr.send(form);
  });
}

/** Full flow: get an upload URL, upload directly, then tell the API it's done. */
export async function uploadReceipt(
  file: File,
  onProgress: (fraction: number) => void,
): Promise<ReceiptDetail> {
  const { receipt_id, upload_url, fields } = await receiptsApi.uploadUrl({
    filename: file.name,
    content_type: file.type,
    size_bytes: file.size,
  });
  await postFile(upload_url, fields, file, onProgress);
  return receiptsApi.complete(receipt_id);
}
