import type { BaseMessage } from "@langchain/core/messages";

import type { AgentScenario, AgentTier } from "@/core/settings/local";

import type { AgentThread } from "./types";

export function pathOfThread(threadId: string) {
  return `/workspace/chats/${threadId}`;
}

export interface ThreadDisplayContextSnapshot {
  model_name?: string;
  scenario?: AgentScenario;
  tier?: AgentTier;
}

export function buildThreadDisplayMetadata(
  context: ThreadDisplayContextSnapshot,
) {
  const metadata: Record<string, string> = {};

  if (context.model_name) {
    metadata.model_name = context.model_name;
  }
  if (context.scenario) {
    metadata.agent_scenario = context.scenario;
  }
  if (context.tier) {
    metadata.agent_tier = context.tier;
  }

  return metadata;
}

export function readThreadDisplayMetadata(
  metadata: unknown,
): ThreadDisplayContextSnapshot | null {
  if (!metadata || typeof metadata !== "object") {
    return null;
  }

  const record = metadata as Record<string, unknown>;
  const model_name =
    typeof record.model_name === "string" ? record.model_name : undefined;
  const scenario =
    record.agent_scenario === "research" || record.agent_scenario === "qa"
      ? record.agent_scenario
      : undefined;
  const tier =
    record.agent_tier === "pro" || record.agent_tier === "ultra"
      ? record.agent_tier
      : undefined;

  if (!model_name && !scenario && !tier) {
    return null;
  }

  return {
    model_name,
    scenario,
    tier,
  };
}

export function textOfMessage(message: BaseMessage) {
  if (typeof message.content === "string") {
    return message.content;
  } else if (Array.isArray(message.content)) {
    return message.content.find((part) => part.type === "text" && part.text)
      ?.text as string;
  }
  return null;
}

export function titleOfThread(thread: AgentThread) {
  const title = thread.values?.title;
  if (title && typeof title === "string") {
    return title;
  }
  return "Untitled";
}
