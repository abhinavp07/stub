import { NextResponse, type NextRequest } from "next/server";

const AUTH_COOKIE = "access_token";
const AUTH_PAGES = ["/login", "/signup"];

/**
 * Redirects based on whether the auth cookie is present. This is a UX convenience only; the
 * API validates the JWT on every request and the client redirects to /login on a 401.
 */
export function middleware(req: NextRequest) {
  const { pathname, search } = req.nextUrl;
  const loggedIn = req.cookies.has(AUTH_COOKIE);
  const isAuthPage = AUTH_PAGES.includes(pathname);

  if (!loggedIn && !isAuthPage) {
    const url = new URL("/login", req.url);
    if (pathname !== "/") url.searchParams.set("next", pathname + search);
    return NextResponse.redirect(url);
  }
  if (loggedIn && isAuthPage) {
    return NextResponse.redirect(new URL("/dashboard", req.url));
  }
  return NextResponse.next();
}

export const config = {
  // App pages only. /api is excluded so uploads stream straight through the rewrite.
  matcher: [
    "/",
    "/login",
    "/signup",
    "/dashboard/:path*",
    "/receipts/:path*",
    "/upload/:path*",
    "/categories/:path*",
    "/budgets/:path*",
  ],
};
