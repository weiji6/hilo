import type { ToolCall } from "@langchain/core/messages";
import type { AIMessage } from "@langchain/langgraph-sdk";

import type { Translations } from "../i18n";
import { hasToolCalls } from "../messages/utils";

export function explainLastToolCall(message: AIMessage, t: Translations) {
  if (hasToolCalls(message)) {
    const lastToolCall = message.tool_calls![message.tool_calls!.length - 1]!;
    return explainToolCall(lastToolCall, t);
  }
  return t.common.thinking;
}

export function explainToolCall(toolCall: ToolCall, t: Translations) {
  return getToolCallLabel(toolCall.name, toolCall.args, t);
}

export function getToolCallLabel(
  name: string,
  args: Record<string, unknown>,
  t: Translations,
) {
  if (name === "web_search") {
    const query = getStringArg(args, "query");
    return query ? t.toolCalls.searchOnWebFor(query) : t.toolCalls.searchForRelatedInfo;
  }
  if (name === "image_search") {
    const query = getStringArg(args, "query");
    return query
      ? t.toolCalls.searchForRelatedImagesFor(query)
      : t.toolCalls.searchForRelatedImages;
  }
  if (name === "web_fetch") {
    return t.toolCalls.viewWebPage;
  }
  if (name === "present_files") {
    return t.toolCalls.presentFiles;
  }
  if (name === "write_todos") {
    return t.toolCalls.writeTodos;
  }
  if (name === "book_search") {
    return t.toolCalls.searchBookCatalog;
  }
  if (name === "knowledge_search") {
    return explainKnowledgeSearch(args, t);
  }
  if (name === "knowledge_locate") {
    return t.toolCalls.locateKnowledgePassage;
  }
  if (name === "knowledge_checkpoint") {
    return t.toolCalls.writeKnowledgeCheckpoint;
  }
  if (name === "ask_clarification") {
    return t.toolCalls.needYourHelp;
  }

  const description = getStringArg(args, "description");
  if (description) {
    return description;
  }

  if (name === "ls") {
    return t.toolCalls.listFolder;
  }
  if (name === "read_file") {
    return t.toolCalls.readFile;
  }
  if (name === "write_file" || name === "str_replace") {
    return t.toolCalls.writeFile;
  }
  if (name === "bash") {
    return t.toolCalls.executeCommand;
  }

  return t.toolCalls.useTool(name);
}

function explainKnowledgeSearch(
  args: Record<string, unknown>,
  t: Translations,
) {
  const scopes = parseScopes(args.scopes ?? args.scope);
  if (scopes.length === 1) {
    if (scopes[0] === "user") {
      return t.toolCalls.searchYourNotes;
    }
    if (scopes[0] === "global") {
      return t.toolCalls.searchBookCatalog;
    }
    if (scopes[0] === "thread") {
      return t.toolCalls.searchThreadMaterials;
    }
  }
  return t.toolCalls.searchKnowledgeBase;
}

function getStringArg(args: Record<string, unknown>, key: string) {
  const value = args[key];
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function parseScopes(value: unknown) {
  if (typeof value === "string") {
    return value
      .split(",")
      .map((item) => item.trim().toLowerCase())
      .filter(Boolean);
  }
  if (Array.isArray(value)) {
    return value
      .filter((item): item is string => typeof item === "string")
      .map((item) => item.trim().toLowerCase())
      .filter(Boolean);
  }
  return [];
}
