import type { AIMessage } from "@langchain/langgraph-sdk";

export interface Subtask {
  id: string;
  status: "in_progress" | "completed" | "failed";
  subagent_type?: string;
  description: string;
  latestMessage?: AIMessage;
  messages?: AIMessage[];
  prompt?: string;
  result?: string;
  summary?: string;
  findings?: string[];
  citations?: string[];
  openQuestions?: string[];
  error?: string;
  executionTimeSeconds?: number;
}
