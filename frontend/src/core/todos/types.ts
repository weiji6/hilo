import type { AIMessage } from "@langchain/langgraph-sdk";
import type { KnowledgeCitationRegistryItem } from "../threads";

export interface AssignedBook {
  doc_id: string;
  title: string;
}

export interface Todo {
  id?: string;
  content?: string;
  status?: "pending" | "in_progress" | "completed" | "failed";
  task_id?: string;
  task_prompt?: string;
  task_description?: string;
  subagent_type?: "general-purpose" | "bash" | string;
  latest_message?: AIMessage;
  stream_messages?: AIMessage[];
  result?: string;
  result_summary?: string;
  structured_summary?: string;
  structured_findings?: string[];
  structured_citations?: string[];
  structured_gaps?: string[];
  citation_registry?: KnowledgeCitationRegistryItem[];
  assigned_books?: AssignedBook[];
  error?: string;
  execution_time_seconds?: number;
  executionTimeSeconds?: number;
  startedAt?: number;
}
