import { type BaseMessage } from "@langchain/core/messages";
import type { Thread } from "@langchain/langgraph-sdk";

import type { Todo } from "../todos";

export interface AgentThreadState extends Record<string, unknown> {
  title: string;
  messages: BaseMessage[];
  artifacts: string[];
  todos?: Todo[];
  subtasks_cancel_requested_at?: string | null;
  knowledge_citation_registry?: KnowledgeCitationRegistryItem[];
}

export interface KnowledgeCitationRegistryItem {
  id?: string | number | null;
  label?: string | null;
  url?: string | null;
}

export interface AgentThread extends Thread<AgentThreadState> {}

export interface AgentThreadContext extends Record<string, unknown> {
  thread_id: string;
  model_name: string | undefined;
  thinking_enabled: boolean;
  is_plan_mode: boolean;
  subagent_enabled: boolean;
  selected_doc_ids?: string[];
  selected_sources_scope?: Array<"global" | "thread" | "user">;
  selected_materials?: Array<{
    doc_id: string;
    title: string;
    filename?: string | null;
    scope?: "global" | "thread" | "user" | null;
  }>;
  /** 问答模式：系统提示会偏向直接作答 */
  qa_mode?: boolean;
  /** 问答 · 极简：提示模型用最短文字回答 */
  concise_answers?: boolean;
}
