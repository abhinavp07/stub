import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import UploadPage from "@/app/(app)/upload/page";
import { ToastProvider } from "@/components/Toast";

const uploadReceipt = vi.fn();
vi.mock("@/lib/upload", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/upload")>();
  return { ...actual, uploadReceipt: (...args: unknown[]) => uploadReceipt(...args) };
});

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <ToastProvider>
        <UploadPage />
      </ToastProvider>
    </QueryClientProvider>,
  );
}

const file = (name: string, type = "image/jpeg", size = 1000) =>
  new File([new Uint8Array(size)], name, { type });

describe("Upload page", () => {
  afterEach(() => uploadReceipt.mockReset());

  it("uploads several files independently; one failure doesn't block the rest", async () => {
    uploadReceipt.mockImplementation(async (f: File, onProgress: (p: number) => void) => {
      onProgress(0.5);
      if (f.name === "bad.jpg") throw new Error("Network error during upload");
      return { id: `id-${f.name}` };
    });
    renderPage();
    const user = userEvent.setup({ applyAccept: false });
    await user.upload(screen.getByLabelText("Choose receipt files"), [
      file("a.jpg"),
      file("bad.jpg"),
      file("c.pdf", "application/pdf"),
      file("notes.txt", "text/plain"),
    ]);

    const list = screen.getByRole("list", { name: "Uploads" });
    await waitFor(() => expect(within(list).getAllByText("View receipt")).toHaveLength(2));
    expect(within(list).getByText("Network error during upload")).toBeInTheDocument();
    // Rejected on the client, never sent.
    expect(within(list).getByText("Only JPG, PNG and PDF files are supported")).toBeInTheDocument();
    expect(uploadReceipt).toHaveBeenCalledTimes(3);
    expect(screen.getByText("a.jpg").closest("li")).toHaveTextContent("View receipt");
    expect(screen.getByText("c.pdf").closest("li")).toHaveTextContent("View receipt");
  });

  it("rejects files over 10 MB before uploading", async () => {
    renderPage();
    const user = userEvent.setup();
    await user.upload(
      screen.getByLabelText("Choose receipt files"),
      file("huge.jpg", "image/jpeg", 10 * 1024 * 1024 + 1),
    );
    expect(await screen.findByText("Files must be 10 MB or smaller")).toBeInTheDocument();
    expect(uploadReceipt).not.toHaveBeenCalled();
  });
});
