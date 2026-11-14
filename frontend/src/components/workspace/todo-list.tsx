import {
  BookOpenIcon,
  CheckCircle2Icon,
  ChevronUpIcon,
  CircleDotIcon,
  ClockIcon,
  ListTodoIcon,
  Loader2Icon,
  XCircleIcon,
} from "lucide-react";
import { useMemo } from "react";

import { useI18n } from "@/core/i18n/hooks";
import { hasToolCalls } from "@/core/messages/utils";
import { useSubtask } from "@/core/tasks/context";
import type { Todo } from "@/core/todos";
import { explainLastToolCall } from "@/core/tools/utils";
import { cn } from "@/lib/utils";

import {
  QueueItem,
  QueueItemContent,
  QueueItemIndicator,
  QueueList,
} from "../ai-elements/queue";

export function TodoList({
  className,
  todos,
  collapsed = false,
  hidden = false,
  onToggle,
  onSelectTodo,
  selectedTodoId,
}: {
  className?: string;
  todos: Todo[];
  collapsed?: boolean;
  hidden?: boolean;
  onToggle?: () => void;
  onSelectTodo?: (todo: Todo) => void;
  selectedTodoId?: string | null;
}) {
  const completedCount = todos.filter((t) => t.status === "completed").length;
  const runningCount = todos.filter((t) => t.status === "in_progress").length;
  const failedCount = todos.filter((t) => t.status === "failed").length;
  return (
    <div
      className={cn(
        "flex h-fit w-full flex-col overflow-hidden rounded-t-2xl border border-border/50 bg-background/80 shadow-2xl backdrop-blur-xl transition-all duration-300 ease-in-out",
        hidden ? "pointer-events-none translate-y-12 opacity-0" : "translate-y-0 opacity-100",
        className,
      )}
    >
      <header
        className={cn(
          "flex min-h-10 shrink-0 cursor-pointer items-center justify-between px-5 text-sm transition-colors hover:bg-muted/30",
          collapsed ? "border-b-0" : "border-b border-border/40 bg-muted/20"
        )}
        onClick={() => {
          onToggle?.();
        }}
      >
        <div className="flex items-center gap-2.5 font-medium text-foreground/80">
          <ListTodoIcon className="size-4.5 text-accent" />
          <div className="tracking-tight">To-dos</div>
        </div>
        <div className="flex items-center gap-3">
          {(runningCount > 0 || failedCount > 0) && (
            <div className="text-[10px] font-semibold tracking-widest text-muted-foreground/70 uppercase">
              {runningCount > 0 ? `${runningCount} RUN` : ""}
              {runningCount > 0 && failedCount > 0 ? " · " : ""}
              {failedCount > 0 ? `${failedCount} FAIL` : ""}
            </div>
          )}
          <div className="text-[10px] font-semibold text-muted-foreground/60 uppercase tracking-widest">
            {completedCount}/{todos.length}
          </div>
          <ChevronUpIcon
            className={cn(
              "size-4 text-muted-foreground transition-transform duration-300",
              collapsed ? "" : "rotate-180",
            )}
          />
        </div>
      </header>
      <main
        className={cn(
          "flex grow flex-col overflow-hidden transition-all duration-300 ease-in-out",
          collapsed ? "h-0 opacity-0" : "h-auto max-h-64 opacity-100 py-3",
        )}
      >
        <QueueList className="w-full px-2">
          {todos.map((todo, i) => (
            <TodoListItem
              key={todo.id ?? todo.task_id ?? `${i}:${todo.content ?? ""}`}
              todo={todo}
              selected={selectedTodoId === (todo.id ?? todo.task_id ?? null)}
              onSelect={onSelectTodo}
            />
          ))}
        </QueueList>
      </main>
    </div>
  );
}

function formatDuration(seconds: number): string {
  if (seconds < 60) {
    return `${Math.round(seconds)}s`;
  }
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return s > 0 ? `${m}m ${s}s` : `${m}m`;
}

function TodoListItem({
  todo,
  selected,
  onSelect,
}: {
  todo: Todo;
  selected: boolean;
  onSelect?: (todo: Todo) => void;
}) {
  const { t } = useI18n();
  const linkedSubtask = useSubtask(todo.task_id ?? "");
  const detailStatus = linkedSubtask?.status ?? todo.status;
  const detailLabel = useMemo(() => {
    if (!detailStatus) {
      return null;
    }
    if (detailStatus === "in_progress" && !todo.task_id) {
      return "主任务执行中";
    }
    if (detailStatus === "pending") {
      return "Pending";
    }
    return t.subtasks[detailStatus];
  }, [detailStatus, t, todo.task_id]);

  const liveAction =
    linkedSubtask?.status === "in_progress" &&
    linkedSubtask.latestMessage &&
    hasToolCalls(linkedSubtask.latestMessage)
      ? explainLastToolCall(linkedSubtask.latestMessage, t)
      : null;

  const executionTime = todo.task_id
    ? (linkedSubtask?.executionTimeSeconds ?? todo.execution_time_seconds)
    : (todo.execution_time_seconds ?? todo.executionTimeSeconds);

  const statusIcon =
    detailStatus === "completed" ? (
      <CheckCircle2Icon className="size-3.5 text-emerald-600" />
    ) : detailStatus === "failed" ? (
      <XCircleIcon className="size-3.5 text-red-500" />
    ) : detailStatus === "in_progress" ? (
      <Loader2Icon className="size-3.5 animate-spin text-primary" />
    ) : (
      <CircleDotIcon className="size-3.5 text-muted-foreground/70" />
    );

  return (
    <QueueItem
      className={cn(
        "py-1.5 transition-all hover:translate-x-0.5",
        selected ? "rounded-xl bg-muted/40" : "",
      )}
    >
      <div className="flex items-start gap-3">
        <QueueItemIndicator
          className={cn(
            "mt-1.5",
            detailStatus === "in_progress"
              ? "border-primary bg-primary shadow-[0_0_8px_rgba(126,51,46,0.4)]"
              : "",
            detailStatus === "failed"
              ? "border-red-500 bg-red-500 shadow-[0_0_8px_rgba(239,68,68,0.35)]"
              : "",
          )}
          completed={detailStatus === "completed"}
        />
        <div className="min-w-0 flex-1">
          <button
            type="button"
            onClick={() => onSelect?.(todo)}
            className={cn(
              "flex w-full items-start gap-2 rounded-lg px-1 py-0.5 text-left",
              "cursor-pointer transition-colors hover:bg-muted/30",
            )}
          >
            <div className="min-w-0 flex-1">
              <QueueItemContent
                className={cn(
                  "font-serif text-[14px] leading-relaxed",
                  detailStatus === "in_progress"
                    ? "font-medium text-foreground"
                    : "text-muted-foreground/90",
                  detailStatus === "completed"
                    ? "text-muted-foreground/50 italic"
                    : "",
                  detailStatus === "failed"
                    ? "text-red-600 dark:text-red-400"
                    : "",
                )}
                completed={detailStatus === "completed"}
              >
                {todo.content}
              </QueueItemContent>
              {todo.assigned_books && todo.assigned_books.length > 0 && (
                <div className="mt-1.5 flex flex-wrap gap-1">
                  {todo.assigned_books.map((book) => (
                    <span
                      key={book.doc_id}
                      className="inline-flex items-center gap-1 rounded-md border border-border/40 bg-muted/30 px-1.5 py-0.5 text-[10px] text-muted-foreground/70"
                    >
                      <BookOpenIcon className="size-2.5 shrink-0" />
                      {book.title}
                    </span>
                  ))}
                </div>
              )}
              {(detailLabel ?? liveAction) && (
                <div className="mt-1 flex items-center gap-1.5 text-[11px] text-muted-foreground/75">
                  {statusIcon}
                  <span className="truncate">{liveAction ?? detailLabel}</span>
                  {executionTime != null && detailStatus !== "in_progress" && (
                    <span className="flex shrink-0 items-center gap-0.5 opacity-60">
                      <ClockIcon className="size-3" />
                      {formatDuration(executionTime)}
                    </span>
                  )}
                </div>
              )}
            </div>
          </button>
        </div>
      </div>
    </QueueItem>
  );
}
