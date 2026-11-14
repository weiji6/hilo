import type { NextRequest } from "next/server";

import { env } from "@/env";
import { auth } from "@/server/better-auth";

export const dynamic = "force-dynamic";

const DEFAULT_LANGGRAPH_BASE_URL = "http://127.0.0.1:2024";
const JSON_CONTENT_TYPE = "application/json";
const DEFAULT_OWNERSHIP_CACHE_TTL_MS = 30_000;
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

type AuthenticatedSession = NonNullable<
  Awaited<ReturnType<typeof auth.api.getSession>>
>;

type ThreadOwnershipCacheEntry = {
  ownerId: string;
  expiresAt: number;
};

const threadOwnershipCache = new Map<string, ThreadOwnershipCacheEntry>();

function getMetadataRecord(body?: Record<string, unknown>) {
  const metadata = body?.metadata;
  return metadata && typeof metadata === "object"
    ? (metadata as Record<string, unknown>)
    : {};
}

function getOwnershipCacheTtlMs() {
  const rawValue = process.env.SECURE_LANGGRAPH_OWNERSHIP_CACHE_TTL_MS;
  if (!rawValue) {
    return DEFAULT_OWNERSHIP_CACHE_TTL_MS;
  }

  const parsed = Number(rawValue);
  if (!Number.isFinite(parsed) || parsed < 0) {
    return DEFAULT_OWNERSHIP_CACHE_TTL_MS;
  }

  return parsed;
}

function getCachedThreadOwner(threadId: string) {
  const cached = threadOwnershipCache.get(threadId);
  if (!cached) {
    return null;
  }

  if (cached.expiresAt <= nowMs()) {
    threadOwnershipCache.delete(threadId);
    return null;
  }

  return cached.ownerId;
}

function setCachedThreadOwner(threadId: string, ownerId: string) {
  const ttlMs = getOwnershipCacheTtlMs();
  if (ttlMs <= 0) {
    threadOwnershipCache.delete(threadId);
    return;
  }

  threadOwnershipCache.set(threadId, {
    ownerId,
    expiresAt: nowMs() + ttlMs,
  });
}

function clearCachedThreadOwner(threadId: string) {
  threadOwnershipCache.delete(threadId);
}

function getUpstreamBaseUrl() {
  return process.env.LANGGRAPH_BASE_URL ??
    process.env.NEXT_PUBLIC_LANGGRAPH_BASE_URL ??
    DEFAULT_LANGGRAPH_BASE_URL;
}

function buildUpstreamUrl(path: string[], request: NextRequest) {
  const url = new URL(path.join("/"), `${getUpstreamBaseUrl()}/`);
  url.search = request.nextUrl.search;
  return url;
}

function buildForwardHeaders(request: NextRequest) {
  const headers = new Headers(request.headers);
  for (const header of HOP_BY_HOP_HEADERS) {
    headers.delete(header);
  }
  return headers;
}

function nowMs() {
  return Date.now();
}

function logSecureLangGraphTiming(
  stage: string,
  payload: Record<string, string | number | boolean | undefined>,
) {
  const parts = Object.entries(payload)
    .filter(([, value]) => value !== undefined)
    .map(([key, value]) => `${key}=${value}`);
  console.info(`[secure-langgraph] ${stage} ${parts.join(" ")}`.trim());
}

async function parseRequestBody(request: NextRequest) {
  if (request.method === "GET" || request.method === "HEAD") {
    return { rawBody: undefined, jsonBody: undefined as unknown };
  }

  const rawBody = await request.text();
  const contentType = request.headers.get("content-type") ?? "";
  if (!rawBody || !contentType.includes(JSON_CONTENT_TYPE)) {
    return { rawBody, jsonBody: undefined as unknown };
  }

  return {
    rawBody,
    jsonBody: JSON.parse(rawBody) as Record<string, unknown>,
  };
}

function serializeBody(body: unknown, fallbackRawBody?: string) {
  if (body === undefined) {
    return fallbackRawBody;
  }
  return JSON.stringify(body);
}

function jsonResponse(body: unknown, status: number) {
  return new Response(JSON.stringify(body), {
    status,
    headers: {
      "content-type": `${JSON_CONTENT_TYPE}; charset=utf-8`,
    },
  });
}

function upstreamUnavailableResponse(error: unknown) {
  const message =
    error instanceof Error ? error.message : "Unable to reach LangGraph upstream";
  return jsonResponse(
    {
      message: "LangGraph upstream unavailable",
      detail: message,
      upstream: getUpstreamBaseUrl(),
    },
    502,
  );
}

async function getAuthenticatedSession(request: NextRequest) {
  if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
    return null;
  }

  return auth.api.getSession({
    headers: request.headers,
  });
}

async function fetchUpstreamThread(threadId: string) {
  const startedAt = nowMs();
  const response = await fetch(`${getUpstreamBaseUrl()}/threads/${threadId}`, {
    headers: {
      accept: JSON_CONTENT_TYPE,
    },
    cache: "no-store",
  });
  logSecureLangGraphTiming("fetch_thread", {
    thread_id: threadId,
    status: response.status,
    elapsed_ms: nowMs() - startedAt,
  });

  if (!response.ok) {
    return {
      response,
      thread: null as null | Record<string, unknown>,
    };
  }

  return {
    response,
    thread: (await response.json()) as Record<string, unknown>,
  };
}

async function ensureThreadOwnership(
  threadId: string,
  session: AuthenticatedSession,
) {
  const startedAt = nowMs();
  const cachedOwnerId = getCachedThreadOwner(threadId);
  if (cachedOwnerId) {
    const ownerMatch = cachedOwnerId === session.user.id;
    logSecureLangGraphTiming("ownership_cache", {
      thread_id: threadId,
      hit: true,
      owner_match: ownerMatch,
    });
    if (ownerMatch) {
      logSecureLangGraphTiming("ownership_check", {
        thread_id: threadId,
        owner_missing: false,
        owner_match: true,
        cached: true,
        elapsed_ms: nowMs() - startedAt,
      });
      return null;
    }

    logSecureLangGraphTiming("ownership_check", {
      thread_id: threadId,
      owner_missing: false,
      owner_match: false,
      cached: true,
      elapsed_ms: nowMs() - startedAt,
    });
    return jsonResponse({ message: "Forbidden" }, 403);
  }

  logSecureLangGraphTiming("ownership_cache", {
    thread_id: threadId,
    hit: false,
  });

  const { response, thread } = await fetchUpstreamThread(threadId);
  if (!response.ok || !thread) {
    clearCachedThreadOwner(threadId);
    logSecureLangGraphTiming("ownership_check_failed", {
      thread_id: threadId,
      status: response.status,
      elapsed_ms: nowMs() - startedAt,
    });
    return new Response(response.body, {
      status: response.status,
      headers: response.headers,
    });
  }

  const metadata =
    thread.metadata && typeof thread.metadata === "object"
      ? (thread.metadata as Record<string, unknown>)
      : {};
  const ownerId =
    typeof metadata.user_id === "string" ? metadata.user_id : undefined;

  if (!ownerId) {
    const claimStartedAt = nowMs();
    const claimResponse = await fetch(
      `${getUpstreamBaseUrl()}/threads/${threadId}`,
      {
        method: "PATCH",
        headers: {
          "content-type": JSON_CONTENT_TYPE,
          accept: JSON_CONTENT_TYPE,
        },
        body: JSON.stringify({
          metadata: {
            ...metadata,
            user_id: session.user.id,
          },
        }),
      },
    );
    logSecureLangGraphTiming("ownership_claim", {
      thread_id: threadId,
      status: claimResponse.status,
      elapsed_ms: nowMs() - claimStartedAt,
    });

    if (!claimResponse.ok) {
      return new Response(claimResponse.body, {
        status: claimResponse.status,
        headers: claimResponse.headers,
      });
    }

    setCachedThreadOwner(threadId, session.user.id);

    logSecureLangGraphTiming("ownership_check", {
      thread_id: threadId,
      owner_missing: true,
      elapsed_ms: nowMs() - startedAt,
    });
    return null;
  }

  setCachedThreadOwner(threadId, ownerId);

  if (ownerId !== session.user.id) {
    logSecureLangGraphTiming("ownership_check", {
      thread_id: threadId,
      owner_missing: false,
      owner_match: false,
      elapsed_ms: nowMs() - startedAt,
    });
    return jsonResponse({ message: "Forbidden" }, 403);
  }

  logSecureLangGraphTiming("ownership_check", {
    thread_id: threadId,
    owner_missing: false,
    owner_match: true,
    elapsed_ms: nowMs() - startedAt,
  });
  return null;
}

function isThreadScopedPath(path: string[]) {
  return (
    path[0] === "threads" &&
    typeof path[1] === "string" &&
    path[1] !== "search" &&
    path[1] !== "count"
  );
}

async function proxyToLangGraph(request: NextRequest, path: string[]) {
  const startedAt = nowMs();
  const pathText = `/${path.join("/")}`;
  try {
    const sessionStartedAt = nowMs();
    const session = await getAuthenticatedSession(request);
    const sessionElapsedMs = nowMs() - sessionStartedAt;
    if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" && !session) {
      logSecureLangGraphTiming("request", {
        method: request.method,
        path: pathText,
        status: 401,
        session_ms: sessionElapsedMs,
        total_ms: nowMs() - startedAt,
      });
      return jsonResponse({ message: "Unauthorized" }, 401);
    }

    const parseStartedAt = nowMs();
    const { rawBody, jsonBody } = await parseRequestBody(request);
    const parseElapsedMs = nowMs() - parseStartedAt;
    let nextJsonBody = jsonBody as Record<string, unknown> | undefined;

    if (session && path[0] === "threads" && request.method === "POST") {
      if (path.length === 1) {
        nextJsonBody = {
          ...(nextJsonBody ?? {}),
          metadata: {
            ...getMetadataRecord(nextJsonBody),
            user_id: session.user.id,
          },
        };
      } else if (path[1] === "search" || path[1] === "count") {
        nextJsonBody = {
          ...(nextJsonBody ?? {}),
          metadata: {
            ...getMetadataRecord(nextJsonBody),
            user_id: session.user.id,
          },
        };
      }
    }

    let ownershipElapsedMs = 0;
    if (session && isThreadScopedPath(path)) {
      const ownershipStartedAt = nowMs();
      const ownershipResponse = await ensureThreadOwnership(path[1]!, session);
      ownershipElapsedMs = nowMs() - ownershipStartedAt;
      if (ownershipResponse) {
        logSecureLangGraphTiming("request", {
          method: request.method,
          path: pathText,
          status: ownershipResponse.status,
          session_ms: sessionElapsedMs,
          parse_ms: parseElapsedMs,
          ownership_ms: ownershipElapsedMs,
          total_ms: nowMs() - startedAt,
        });
        return ownershipResponse;
      }

      if (
        request.method === "PATCH" &&
        (path.length === 2 || (path.length === 3 && path[2] === "state"))
      ) {
        nextJsonBody = {
          ...(nextJsonBody ?? {}),
          metadata: {
            ...getMetadataRecord(nextJsonBody),
            user_id: session.user.id,
          },
        };
      }
    }

    const upstreamStartedAt = nowMs();
    const upstreamResponse = await fetch(buildUpstreamUrl(path, request), {
      method: request.method,
      headers: buildForwardHeaders(request),
      body: serializeBody(nextJsonBody, rawBody),
      cache: "no-store",
    });
    const upstreamElapsedMs = nowMs() - upstreamStartedAt;
    logSecureLangGraphTiming("request", {
      method: request.method,
      path: pathText,
      status: upstreamResponse.status,
      session_ms: sessionElapsedMs,
      parse_ms: parseElapsedMs,
      ownership_ms: ownershipElapsedMs,
      upstream_ms: upstreamElapsedMs,
      total_ms: nowMs() - startedAt,
    });

    return new Response(upstreamResponse.body, {
      status: upstreamResponse.status,
      headers: upstreamResponse.headers,
    });
  } catch (error) {
    logSecureLangGraphTiming("request_error", {
      method: request.method,
      path: pathText,
      total_ms: nowMs() - startedAt,
      error: error instanceof Error ? error.message : String(error),
    });
    return upstreamUnavailableResponse(error);
  }
}

async function handleRequest(request: NextRequest, context: RouteContext) {
  const { path } = await context.params;
  return proxyToLangGraph(request, path);
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
