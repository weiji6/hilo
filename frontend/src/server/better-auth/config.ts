import { betterAuth } from "better-auth";
import { memoryAdapter } from "better-auth/adapters/memory";
import { createPool, type Pool } from "mysql2/promise";

import { env } from "@/env";

declare global {
  // Reuse the pool across hot reloads in development.
  var __authMySqlPool: Pool | undefined;
}

function createDatabase() {
  if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
    return memoryAdapter({});
  }

  if (!env.DATABASE_URL) {
    throw new Error(
      "DATABASE_URL is required when authentication is enabled.",
    );
  }

  const pool =
    globalThis.__authMySqlPool ??
    createPool({
      uri: env.DATABASE_URL,
      connectionLimit: 10,
    });

  if (process.env.NODE_ENV !== "production") {
    globalThis.__authMySqlPool = pool;
  }

  return pool;
}

export const auth = betterAuth({
  database: createDatabase(),
  baseURL: env.BETTER_AUTH_BASE_URL,
  secret: env.BETTER_AUTH_SECRET,
  trustedOrigins: [
    env.BETTER_AUTH_BASE_URL,
    "http://localhost:2026",
    "http://127.0.0.1:2026",
  ].filter((origin): origin is string => Boolean(origin)),
  emailAndPassword: {
    enabled: true,
  },
});

export type Session = typeof auth.$Infer.Session;
