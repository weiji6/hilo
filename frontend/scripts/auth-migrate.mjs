import "dotenv/config";

import { betterAuth } from "better-auth";
import { getMigrations } from "better-auth/db";
import { createPool } from "mysql2/promise";

const databaseUrl = process.env.DATABASE_URL;
const secret = process.env.BETTER_AUTH_SECRET;
const baseURL = process.env.BETTER_AUTH_BASE_URL;

if (!databaseUrl) {
  throw new Error("DATABASE_URL is required to run auth migrations.");
}

if (!secret) {
  throw new Error("BETTER_AUTH_SECRET is required to run auth migrations.");
}

const pool = createPool({
  uri: databaseUrl,
  connectionLimit: 10,
});

const auth = betterAuth({
  database: pool,
  baseURL,
  secret,
  emailAndPassword: {
    enabled: true,
  },
});

const { runMigrations } = await getMigrations(auth.options);

try {
  await runMigrations();
  console.log("Better Auth MySQL migrations completed.");
} finally {
  await pool.end();
}
