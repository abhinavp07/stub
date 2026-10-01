"use client";

import { useQuery, useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";

import { authApi, metaApi } from "@/lib/api";

const NAV = [
  { href: "/dashboard", label: "Dashboard" },
  { href: "/receipts", label: "Receipts" },
  { href: "/upload", label: "Upload" },
  { href: "/budgets", label: "Budgets" },
  { href: "/categories", label: "Categories" },
];

export function useMe() {
  return useQuery({ queryKey: ["me"], queryFn: authApi.me, staleTime: 5 * 60_000 });
}

function DemoModeBanner() {
  const { data } = useQuery({
    queryKey: ["health"],
    queryFn: metaApi.health,
    staleTime: Infinity,
  });
  if (data?.textract_mode !== "mock") return null;
  return (
    <div role="note" className="border-b border-amber-200 bg-amber-50 text-sm text-amber-900">
      <p className="mx-auto max-w-6xl px-4 py-2">
        <strong className="font-semibold">Demo mode:</strong> receipts aren&apos;t actually read.
        Files from <code className="rounded bg-amber-100 px-1">demo-receipts/</code> return sample
        data; anything else comes back blank for you to fill in. Set{" "}
        <code className="rounded bg-amber-100 px-1">TEXTRACT_MODE=aws</code> to read real receipts
        (see the README).
      </p>
    </div>
  );
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const queryClient = useQueryClient();
  const { data: me } = useMe();

  async function logout() {
    await authApi.logout().catch(() => {});
    queryClient.clear();
    router.replace("/login");
    router.refresh();
  }

  return (
    <div className="flex min-h-screen flex-col">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:rounded focus:bg-white focus:px-3 focus:py-2 focus:shadow"
      >
        Skip to content
      </a>
      <header className="border-b border-gray-200 bg-white">
        <div className="mx-auto flex max-w-6xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
          <Link href="/dashboard" className="font-semibold tracking-tight">
            Stub
          </Link>
          <nav aria-label="Main" className="-mx-1 flex max-w-full gap-1 overflow-x-auto px-1">
            {NAV.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  aria-current={active ? "page" : undefined}
                  className={`rounded-md px-3 py-1.5 text-sm font-medium focus-visible:outline-2 focus-visible:outline-blue-600 ${
                    active ? "bg-gray-900 text-white" : "text-gray-700 hover:bg-gray-100"
                  }`}
                >
                  {item.label}
                </Link>
              );
            })}
          </nav>
          <div className="ml-auto flex items-center gap-3 text-sm">
            {me && (
              <span className="hidden text-gray-600 sm:inline" title={me.email}>
                {me.display_name || me.email}
              </span>
            )}
            <button
              type="button"
              onClick={logout}
              className="rounded-md px-2 py-1 text-gray-700 hover:bg-gray-100 focus-visible:outline-2 focus-visible:outline-blue-600"
            >
              Log out
            </button>
          </div>
        </div>
      </header>
      <DemoModeBanner />
      <main id="main" className="mx-auto w-full max-w-6xl flex-1 px-4 py-6">
        {children}
      </main>
    </div>
  );
}
