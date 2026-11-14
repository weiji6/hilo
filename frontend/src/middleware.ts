import { getSessionCookie } from "better-auth/cookies";
import { type NextRequest, NextResponse } from "next/server";

export function middleware(request: NextRequest) {
  if (process.env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
    return NextResponse.next();
  }

  const sessionCookie = getSessionCookie(request);
  if (sessionCookie) {
    return NextResponse.next();
  }

  const authURL = new URL("/auth", request.url);
  const nextPath = `${request.nextUrl.pathname}${request.nextUrl.search}`;
  authURL.searchParams.set("next", nextPath);
  return NextResponse.redirect(authURL);
}

export const config = {
  matcher: ["/workspace/:path*"],
};
