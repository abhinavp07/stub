import { describe, expect, it } from "vitest";

import { MAX_UPLOAD_BYTES, validateFile } from "@/lib/upload";

describe("validateFile", () => {
  it.each(["image/jpeg", "image/png", "application/pdf"])("accepts %s", (type) => {
    expect(validateFile({ type, size: 1000 })).toBeNull();
  });

  it("accepts exactly 10 MB", () => {
    expect(validateFile({ type: "image/jpeg", size: MAX_UPLOAD_BYTES })).toBeNull();
  });

  it.each(["image/gif", "image/heic", "text/plain", ""])("rejects %s", (type) => {
    expect(validateFile({ type, size: 1000 })).toBe("Only JPG, PNG and PDF files are supported");
  });

  it("rejects files over 10 MB", () => {
    expect(validateFile({ type: "image/png", size: MAX_UPLOAD_BYTES + 1 })).toBe(
      "Files must be 10 MB or smaller",
    );
  });

  it("rejects empty files", () => {
    expect(validateFile({ type: "image/png", size: 0 })).toBe("File is empty");
  });
});
