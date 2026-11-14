import type { NextRequest } from "next/server";

import { env } from "@/env";
import { auth } from "@/server/better-auth";

export const dynamic = "force-dynamic";

const DEFAULT_BACKEND_BASE_URL = "http://127.0.0.1:8001";
const HOP_BY_HOP_HEADERS = new Set([
  "connection",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

type RouteContext = {
  params: Promise<{
    path: string[];
  }>;
};

function getBackendBaseUrl() {
  return process.env.BACKEND_BASE_URL ??
    env.NEXT_PUBLIC_BACKEND_BASE_URL ??
    DEFAULT_BACKEND_BASE_URL;
}

function upstreamUnavailableResponse(error: unknown) {
  const detail =
    error instanceof Error ? error.message : "Unable to reach backend upstream";
  return new Response(
    JSON.stringify({
      message: "Backend upstream unavailable",
      detail,
      upstream: getBackendBaseUrl(),
    }),
    {
      status: 502,
      headers: {
        "content-type": "application/json; charset=utf-8",
      },
    },
  );
}

function buildForwardHeaders(request: NextRequest) {
  const headers = new Headers(request.headers);
  for (const header of HOP_BY_HOP_HEADERS) {
    headers.delete(header);
  }
  return headers;
}

function rewriteUserPath(path: string[], userId: string) {
  if (path[0] !== "users" || path[1] !== "me") {
    throw new Error("Only /users/me knowledge routes are supported");
  }
  return ["users", userId, ...path.slice(2)];
}

async function getRequestBody(request: NextRequest) {
  if (request.method === "GET" || request.method === "HEAD") {
    return undefined;
  }
  return request.body;
}

async function handleRequest(request: NextRequest, context: RouteContext) {
  try {
    if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
      return new Response(JSON.stringify({ message: "Personal knowledge is unavailable in static mode" }), {
        status: 404,
        headers: {
          "content-type": "application/json; charset=utf-8",
        },
      });
    }

    const session = await auth.api.getSession({
      headers: request.headers,
    });
    if (!session) {
      return new Response(JSON.stringify({ message: "Unauthorized" }), {
        status: 401,
        headers: {
          "content-type": "application/json; charset=utf-8",
        },
      });
    }

    const { path } = await context.params;
    let rewrittenPath: string[];
    try {
      rewrittenPath = rewriteUserPath(path, session.user.id);
    } catch (error) {
      return new Response(JSON.stringify({ message: (error as Error).message }), {
        status: 400,
        headers: {
          "content-type": "application/json; charset=utf-8",
        },
      });
    }

    const upstreamUrl = new URL(`/api/${rewrittenPath.join("/")}`, getBackendBaseUrl());
    upstreamUrl.search = request.nextUrl.search;
    const body = await getRequestBody(request);
    const upstreamResponse = await fetch(upstreamUrl, {
      method: request.method,
      headers: buildForwardHeaders(request),
      body,
      ...(body ? ({ duplex: "half" } as const) : {}),
      cache: "no-store",
    });

    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      headers: upstreamResponse.headers,
    });
  } catch (error) {
    return upstreamUnavailableResponse(error);
  }
}

export async function GET(request: NextRequest, context: RouteContext) {
  return handleRequest(request, context);
}

export async function POST(request: NextRequest, context: RouteContext) {
  return handleRequest(request, context);
}

export async function PUT(request: NextRequest, context: RouteContext) {
  return handleRequest(request, context);
}

export async function PATCH(request: NextRequest, context: RouteContext) {
  return handleRequest(request, context);
}

export async function DELETE(request: NextRequest, context: RouteContext) {
  return handleRequest(request, context);
}
