"use client";

import type { AIMessage, Message } from "@langchain/langgraph-sdk";
import {
  CheckCircle2Icon,
  CircleDotIcon,
  ClockIcon,
  Loader2Icon,
  XCircleIcon,
} from "lucide-react";
import { useMemo } from "react";

import {
  Message as AIElementMessage,
  MessageContent as AIElementMessageContent,
} from "@/components/ai-elements/message";
import {
  Sheet,
  SheetContent,
  SheetDescription,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { useI18n } from "@/core/i18n/hooks";
import { extractTextFromMessage, hasToolCalls } from "@/core/messages/utils";
import { useRehypeSplitWordsIntoSpans } from "@/core/rehype";
import { useSubtask } from "@/core/tasks/context";
import type { Todo } from "@/core/todos";
import { useThread } from "./messages/context";
import { explainLastToolCall } from "@/core/tools/utils";
import { cn } from "@/lib/utils";

import { MarkdownContent } from "./messages/markdown-content";
import { MessageGroup } from "./messages/message-group";
import { MessageListItem } from "./messages/message-list-item";

function statusLabel(
  status: Todo["status"] | "in_progress" | "completed" | "failed" | undefined,
  t: ReturnType<typeof useI18n>["t"],
) {
  if (!status || status === "pending") {
    return "Pending";
  }
  return t.subtasks[status];
}

function latestProgressText(
  message: AIMessage | undefined,
  detail: string | null,
) {
  if (!message) {
    return detail;
  }
  const text = extractTextFromMessage(message).trim();
  if (text) {
    return text;
  }
  return detail;
}

function buildSyntheticAssistantMessage(id: string, content: string): Message {
  return {
    type: "ai",
    id,
    content,
  } as Message;
}

export function SubtaskDetailSheet({
  open,
  todo,
  onOpenChange,
}: {
  open: boolean;
  todo: Todo | null;
  onOpenChange: (open: boolean) => void;
}) {
  const { t } = useI18n();
  const { thread } = useThread();
  const linkedSubtask = useSubtask(todo?.task_id ?? "");
  const rehypePlugins = useRehypeSplitWordsIntoSpans(false);
  const fallbackLatestMessage =
    linkedSubtask?.latestMessage ?? todo?.latest_message;
  const fallbackStreamingMessages =
    linkedSubtask?.messages ?? todo?.stream_messages ?? [];
  const fallbackResult = linkedSubtask?.result ?? todo?.result;
  const fallbackSummary = linkedSubtask?.summary ?? todo?.structured_summary;
  const fallbackFindings =
    linkedSubtask?.findings ?? todo?.structured_findings ?? [];
  const fallbackCitations =
    linkedSubtask?.citations ?? todo?.structured_citations ?? [];
  const fallbackOpenQuestions =
    linkedSubtask?.openQuestions ?? todo?.structured_gaps ?? [];
  const fallbackError = linkedSubtask?.error ?? todo?.error;
  const executionTimeSeconds = linkedSubtask?.executionTimeSeconds ?? todo?.execution_time_seconds ?? todo?.executionTimeSeconds;
  const threadCitationRegistry = thread.values.knowledge_citation_registry as
    | import("@/core/threads").KnowledgeCitationRegistryItem[]
    | undefined;
  const citationRegistry =
    todo?.citation_registry ?? threadCitationRegistry;

  const detailStatus = linkedSubtask?.status ?? todo?.status;
  const liveAction =
    detailStatus === "in_progress" &&
    fallbackLatestMessage &&
    hasToolCalls(fallbackLatestMessage)
      ? explainLastToolCall(fallbackLatestMessage, t)
      : null;
  const latestProgress = latestProgressText(
    fallbackLatestMessage,
    liveAction ?? (detailStatus === "in_progress" ? "子任务运行中..." : null),
  );
  const streamingMessages = fallbackStreamingMessages as Message[];

  const structuredResultContent = useMemo(() => {
    const sections: string[] = [];
    if (fallbackSummary) {
      sections.push(`## 任务结果\n${fallbackSummary}`);
    }
    if (fallbackFindings.length > 0) {
      sections.push(
        `## 关键发现\n${fallbackFindings.map((item) => `- ${item}`).join("\n")}`,
      );
    }
    if (fallbackCitations.length > 0) {
      sections.push(
        `## 关键引文\n${fallbackCitations.map((item) => `- ${item}`).join("\n")}`,
      );
    }
    if (fallbackOpenQuestions.length > 0) {
      sections.push(
        `## 未解决缺口\n${fallbackOpenQuestions.map((item) => `- ${item}`).join("\n")}`,
      );
    }
    return sections.join("\n\n").trim();
  }, [
    fallbackCitations,
    fallbackFindings,
    fallbackOpenQuestions,
    fallbackSummary,
  ]);

  const renderedResultMessage = useMemo(() => {
    const content = structuredResultContent || fallbackResult;
    if (!content || !todo) {
      return null;
    }
    return buildSyntheticAssistantMessage(
      `${todo.task_id ?? todo.id ?? "subtask"}:result`,
      content,
    );
  }, [fallbackResult, structuredResultContent, todo]);

  const statusIcon = useMemo(() => {
    if (detailStatus === "completed") {
      return <CheckCircle2Icon className="size-4 text-emerald-600" />;
    }
    if (detailStatus === "failed") {
      return <XCircleIcon className="size-4 text-red-500" />;
    }
    if (detailStatus === "in_progress") {
      return <Loader2Icon className="text-primary size-4 animate-spin" />;
    }
    return <CircleDotIcon className="text-muted-foreground/70 size-4" />;
  }, [detailStatus]);

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent side="right" className="w-full gap-0 p-0 sm:max-w-2xl">
        <SheetHeader className="border-border/60 border-b px-6 py-5">
          <SheetTitle className="pr-8 text-base leading-relaxed">
            {todo?.content ?? "子任务详情"}
          </SheetTitle>
          <SheetDescription className="flex items-center gap-2 text-xs">
            {statusIcon}
            <span>{statusLabel(detailStatus, t)}</span>
            {executionTimeSeconds != null && detailStatus !== "in_progress" && (
              <span className="text-muted-foreground/60 flex items-center gap-1">
                <ClockIcon className="size-3" />
                {executionTimeSeconds < 60
                  ? `${Math.round(executionTimeSeconds)}s`
                  : `${Math.floor(executionTimeSeconds / 60)}m ${Math.round(executionTimeSeconds % 60)}s`}
              </span>
            )}
          </SheetDescription>
        </SheetHeader>

        <div className="flex min-h-0 flex-1 flex-col overflow-y-auto px-6 py-6">
          {!todo ? (
            <div className="text-muted-foreground text-sm">未选中子任务。</div>
          ) : (
            <div className="space-y-6">
              {todo.task_id && (
                <div className="text-muted-foreground/70 text-[11px] tracking-widest uppercase">
                  {todo.subagent_type ??
                    linkedSubtask?.subagent_type ??
                    "subagent"}{" "}
                  · {todo.task_id}
                </div>
              )}

              {detailStatus === "in_progress" && !todo.task_id && (
                <AIElementMessage from="assistant">
                  <AIElementMessageContent className="w-full">
                    <MarkdownContent
                      content={
                        "## 下发状态\n这个 todo 目前还没有拿到真实的 subtask task_id。当前看到的是主任务里的进行中项，不是已经下发出去并可独立 streaming 的子任务。"
                      }
                      isLoading={false}
                      rehypePlugins={rehypePlugins}
                      className="my-2 text-red-600 dark:text-red-400"
                      citationRegistry={citationRegistry}
                    />
                  </AIElementMessageContent>
                </AIElementMessage>
              )}

              {streamingMessages.length > 0 ? (
                <MessageGroup
                  messages={streamingMessages}
                  isLoading={detailStatus === "in_progress"}
                  citationRegistry={citationRegistry}
                />
              ) : latestProgress && detailStatus === "in_progress" ? (
                <AIElementMessage from="assistant">
                  <AIElementMessageContent className="w-full">
                    <MarkdownContent
                      content={latestProgress}
                      isLoading={true}
                      rehypePlugins={rehypePlugins}
                      className={cn(
                        "my-2",
                        detailStatus === "in_progress" ? "text-foreground" : "",
                      )}
                      citationRegistry={citationRegistry}
                    />
                  </AIElementMessageContent>
                </AIElementMessage>
              ) : null}

              {renderedResultMessage && (
                <MessageListItem
                  message={renderedResultMessage}
                  isLoading={false}
                  citationRegistry={citationRegistry}
                />
              )}

              {!renderedResultMessage && todo.result_summary && (
                <AIElementMessage from="assistant">
                  <AIElementMessageContent className="w-full">
                    <MarkdownContent
                      content={todo.result_summary}
                      isLoading={false}
                      rehypePlugins={rehypePlugins}
                      className="my-2"
                      citationRegistry={citationRegistry}
                    />
                  </AIElementMessageContent>
                </AIElementMessage>
              )}

              {fallbackError && (
                <AIElementMessage from="assistant">
                  <AIElementMessageContent className="w-full">
                    <MarkdownContent
                      content={fallbackError}
                      isLoading={false}
                      rehypePlugins={rehypePlugins}
                      className="my-2 text-red-600 dark:text-red-400"
                      citationRegistry={citationRegistry}
                    />
                  </AIElementMessageContent>
                </AIElementMessage>
              )}

              {!linkedSubtask &&
                !todo.result_summary &&
                !fallbackError &&
                !todo.task_id &&
                streamingMessages.length === 0 &&
                !fallbackResult && (
                  <div className="text-muted-foreground text-sm">
                    这个 todo 还没有关联到可展示的子任务详情。
                  </div>
                )}
            </div>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
