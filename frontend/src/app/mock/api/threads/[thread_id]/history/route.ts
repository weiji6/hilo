import fs from "fs";
import path from "path";

import type { NextRequest } from "next/server";

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ thread_id: string }> },
) {
  const threadId = (await params).thread_id;
  const demoRoot = path.resolve(process.cwd(), "public/demo/threads");
  const demoPath = path.resolve(demoRoot, threadId, "thread.json");
  if (!demoPath.startsWith(demoRoot + path.sep) || !fs.existsSync(demoPath)) {
    return Response.json({ error: "Demo thread not found" }, { status: 404 });
  }
  const jsonString = fs.readFileSync(demoPath, "utf8");
  const json = JSON.parse(jsonString);
  if (Array.isArray(json.history)) {
    return Response.json(json);
  }
  return Response.json([json]);
}
