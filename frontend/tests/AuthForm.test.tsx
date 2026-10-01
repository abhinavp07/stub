import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { AuthForm } from "@/components/AuthForm";

const replace = vi.fn();
let search = new URLSearchParams();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, refresh: vi.fn() }),
  useSearchParams: () => search,
}));

function renderForm(mode: "login" | "signup") {
  const client = new QueryClient();
  return render(
    <QueryClientProvider client={client}>
      <AuthForm mode={mode} />
    </QueryClientProvider>,
  );
}

function mockFetch(status: number, body: unknown) {
  const fn = vi.fn().mockResolvedValue({
    ok: status < 400,
    status,
    statusText: "",
    json: async () => body,
  });
  vi.stubGlobal("fetch", fn);
  return fn;
}

describe("AuthForm", () => {
  beforeEach(() => {
    search = new URLSearchParams();
    replace.mockReset();
  });
  afterEach(() => vi.unstubAllGlobals());

  it("validates signup fields before calling the API", async () => {
    const fetchMock = mockFetch(201, {});
    renderForm("signup");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "not-an-email");
    await user.type(screen.getByLabelText("Password"), "short");
    await user.type(screen.getByLabelText("Confirm password"), "different");
    await user.click(screen.getByRole("button", { name: "Sign up" }));

    expect(await screen.findByText("Enter a valid email address")).toBeInTheDocument();
    expect(screen.getByText("Use at least 8 characters")).toBeInTheDocument();
    expect(screen.getByText("Passwords don't match")).toBeInTheDocument();
    expect(screen.getByLabelText("Email")).toHaveAttribute("aria-invalid", "true");
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("logs in and goes to the requested page", async () => {
    search = new URLSearchParams({ next: "/receipts/abc" });
    const fetchMock = mockFetch(200, {
      id: "u1",
      email: "a@b.co",
      display_name: null,
      currency: "USD",
    });
    renderForm("login");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "a@b.co");
    await user.type(screen.getByLabelText("Password"), "secret-password");
    await user.click(screen.getByRole("button", { name: "Log in" }));

    await waitFor(() => expect(replace).toHaveBeenCalledWith("/receipts/abc"));
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/auth/login");
    expect(JSON.parse(init.body)).toEqual({ email: "a@b.co", password: "secret-password" });
  });

  it("ignores off-site redirect targets", async () => {
    search = new URLSearchParams({ next: "//evil.example" });
    mockFetch(200, { id: "u1", email: "a@b.co", display_name: null, currency: "USD" });
    renderForm("login");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "a@b.co");
    await user.type(screen.getByLabelText("Password"), "pw");
    await user.click(screen.getByRole("button", { name: "Log in" }));
    await waitFor(() => expect(replace).toHaveBeenCalledWith("/dashboard"));
  });

  it("shows the API's error message", async () => {
    mockFetch(401, { detail: "Invalid email or password" });
    renderForm("login");
    const user = userEvent.setup();
    await user.type(screen.getByLabelText("Email"), "a@b.co");
    await user.type(screen.getByLabelText("Password"), "wrong");
    await user.click(screen.getByRole("button", { name: "Log in" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Invalid email or password");
    expect(replace).not.toHaveBeenCalled();
  });
});
