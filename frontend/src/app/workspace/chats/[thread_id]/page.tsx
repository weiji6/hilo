"use client";

import type { AIMessage, Message } from "@langchain/langgraph-sdk";
import type { UseStream } from "@langchain/langgraph-sdk/react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { FilesIcon, XIcon } from "lucide-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { ConversationEmptyState } from "@/components/ai-elements/conversation";
import { usePromptInputController } from "@/components/ai-elements/prompt-input";
import { Button } from "@/components/ui/button";
import { useSidebar } from "@/components/ui/sidebar";
import { ArtifactFileDetail } from "@/components/workspace/artifacts/artifact-file-detail";
import { ArtifactFileList } from "@/components/workspace/artifacts/artifact-file-list";
import { useArtifacts } from "@/components/workspace/artifacts/context";
import {
  KNOWLEDGE_ARTIFACT_PANEL_DEFAULT_WIDTH,
  KNOWLEDGE_ARTIFACT_PANEL_EXPANDED_WIDTH,
} from "@/components/workspace/artifacts/knowledge-layout";
import { InputBox } from "@/components/workspace/input-box";
import { MessageList } from "@/components/workspace/messages";
import { ThreadContext } from "@/components/workspace/messages/context";
import { SilkRibbon } from "@/components/workspace/silk-ribbon";
import { SubtaskDetailSheet } from "@/components/workspace/subtask-detail-sheet";
import { ThreadTitle } from "@/components/workspace/thread-title";
import { TodoList } from "@/components/workspace/todo-list";
import { Tooltip } from "@/components/workspace/tooltip";
import { Welcome } from "@/components/workspace/welcome";
import { getAPIClient } from "@/core/api";
import { useI18n } from "@/core/i18n/hooks";
import {
  parseSelectedMaterials,
  type SelectedMaterial,
} from "@/core/knowledge/selection";
import { useModels } from "@/core/models/hooks";
import { useNotification } from "@/core/notification/hooks";
import { useLocalSettings } from "@/core/settings";
import { useUpdateSubtask } from "@/core/tasks/context";
import { type AgentThread, type AgentThreadState } from "@/core/threads";
import {
  useSubmitThread,
  useThreadStream,
} from "@/core/threads/hooks";
import {
  buildThreadDisplayMetadata,
  pathOfThread,
  readThreadDisplayMetadata,
  textOfMessage,
  type ThreadDisplayContextSnapshot,
  titleOfThread,
} from "@/core/threads/utils";
import {
  WORKSPACE_TODO_SELECTED_EVENT,
  type Todo,
  type TodoSelectionDetail,
} from "@/core/todos";
import { uuid } from "@/core/utils/uuid";
import { env } from "@/env";
import { cn } from "@/lib/utils";
import { authClient } from "@/server/better-auth/client";

const THREAD_ROUTE_HANDOFF_KEY = "workspace:thread-route-handoff";
const THREAD_ROUTE_HANDOFF_TTL_MS = 15_000;

function readThreadRouteHandoff() {
  if (typeof window === "undefined") {
    return null;
  }

  try {
    const raw = window.sessionStorage.getItem(THREAD_ROUTE_HANDOFF_KEY);
    if (!raw) {
      return null;
    }

    const parsed = JSON.parse(raw) as {
      createdAt?: number;
      context?: ThreadDisplayContextSnapshot;
      threadId?: string;
    };
    if (
      typeof parsed.threadId !== "string" ||
      typeof parsed.createdAt !== "number"
    ) {
      window.sessionStorage.removeItem(THREAD_ROUTE_HANDOFF_KEY);
      return null;
    }

    if (Date.now() - parsed.createdAt > THREAD_ROUTE_HANDOFF_TTL_MS) {
      window.sessionStorage.removeItem(THREAD_ROUTE_HANDOFF_KEY);
      return null;
    }

    return parsed;
  } catch {
    window.sessionStorage.removeItem(THREAD_ROUTE_HANDOFF_KEY);
    return null;
  }
}

function rememberThreadRouteHandoff(
  threadId: string,
  context?: ThreadDisplayContextSnapshot,
) {
  if (typeof window === "undefined") {
    return;
  }

  window.sessionStorage.setItem(
    THREAD_ROUTE_HANDOFF_KEY,
    JSON.stringify({
      context,
      threadId,
      createdAt: Date.now(),
    }),
  );
}

function clearThreadRouteHandoff(threadId?: string) {
  if (typeof window === "undefined") {
    return;
  }

  const handoff = readThreadRouteHandoff();
  if (!handoff) {
    return;
  }

  if (!threadId || handoff.threadId === threadId) {
    window.sessionStorage.removeItem(THREAD_ROUTE_HANDOFF_KEY);
  }
}

type TaskStartedEvent = {
  type: "task_started";
  task_id: string;
  description?: string;
};

type TaskRunningEvent = {
  type: "task_running";
  task_id: string;
  message: AIMessage;
};

type TaskCompletedEvent = {
  type: "task_completed";
  task_id: string;
  result?: string;
  summary?: string;
  findings?: string[];
  citations?: string[];
  open_questions?: string[];
  execution_time_seconds?: number;
};

type TaskFailedEvent = {
  type: "task_failed" | "task_timed_out";
  task_id: string;
  error?: string;
  execution_time_seconds?: number;
};

type TodoBoardUpdatedEvent = {
  type: "todo_board_updated";
  todos: Todo[];
};

type ActiveRun = {
  runId: string;
  threadId: string;
};

function isTaskStartedEvent(event: unknown): event is TaskStartedEvent {
  return (
    typeof event === "object" &&
    event !== null &&
    "type" in event &&
    event.type === "task_started" &&
    "task_id" in event &&
    typeof event.task_id === "string"
  );
}

function isTaskRunningEvent(event: unknown): event is TaskRunningEvent {
  return (
    typeof event === "object" &&
    event !== null &&
    "type" in event &&
    event.type === "task_running" &&
    "task_id" in event &&
    typeof event.task_id === "string" &&
    "message" in event &&
    typeof event.message === "object" &&
    event.message !== null
  );
}

function isTaskCompletedEvent(event: unknown): event is TaskCompletedEvent {
  return (
    typeof event === "object" &&
    event !== null &&
    "type" in event &&
    event.type === "task_completed" &&
    "task_id" in event &&
    typeof event.task_id === "string"
  );
}

function isTaskFailedEvent(event: unknown): event is TaskFailedEvent {
  return (
    typeof event === "object" &&
    event !== null &&
    "type" in event &&
    (event.type === "task_failed" || event.type === "task_timed_out") &&
    "task_id" in event &&
    typeof event.task_id === "string"
  );
}

function isTodoBoardUpdatedEvent(event: unknown): event is TodoBoardUpdatedEvent {
  return (
    typeof event === "object" &&
    event !== null &&
    "type" in event &&
    event.type === "todo_board_updated" &&
    "todos" in event &&
    Array.isArray(event.todos)
  );
}

function readActiveRunId(threadId?: string | null): string | null {
  if (typeof window === "undefined" || !threadId) {
    return null;
  }

  return window.sessionStorage.getItem(`lg:stream:${threadId}`);
}

function clearActiveRunId(threadId?: string | null) {
  if (typeof window === "undefined" || !threadId) {
    return;
  }

  window.sessionStorage.removeItem(`lg:stream:${threadId}`);
}

function normalizeTodoContent(content?: string | null) {
  if (!content) {
    return "";
  }

  return content
    .replace(/\s+/g, " ")
    .replace(/（/g, "(")
    .replace(/）/g, ")")
    .replace(/：/g, ":")
    .trim();
}

function todosMatch(left: Todo | null | undefined, right: Todo | null | undefined) {
  if (!left || !right) {
    return false;
  }

  if (left.task_id && right.task_id && left.task_id === right.task_id) {
    return true;
  }

  if (left.id && right.id && left.id === right.id) {
    return true;
  }

  const leftContent = normalizeTodoContent(left.content);
  const rightContent = normalizeTodoContent(right.content);
  if (!leftContent || !rightContent) {
    return false;
  }

  return (
    leftContent === rightContent ||
    leftContent.includes(rightContent) ||
    rightContent.includes(leftContent)
  );
}

function mergeStreamingMessages(
  previousMessages: AIMessage[] | undefined,
  incomingMessages: AIMessage[],
) {
  const merged = [...(previousMessages ?? [])];

  for (const incoming of incomingMessages) {
    const incomingId = incoming.id;
    if (!incomingId) {
      merged.push(incoming);
      continue;
    }

    const existingIndex = merged.findIndex((message) => message.id === incomingId);
    if (existingIndex >= 0) {
      merged[existingIndex] = incoming;
      continue;
    }

    merged.push(incoming);
  }

  return merged;
}

function mergeTaskEventIntoTodos(
  todos: Todo[] | null,
  event:
    | TaskStartedEvent
    | TaskRunningEvent
    | TaskCompletedEvent
    | TaskFailedEvent,
) {
  if (!todos || todos.length === 0) {
    return todos;
  }

  let changed = false;
  const nextTodos = todos.map((todo) => {
    if (todo.task_id !== event.task_id) {
      return todo;
    }

    changed = true;
    if (event.type === "task_started") {
      return {
        ...todo,
        status: "in_progress" as const,
        task_description: event.description ?? todo.task_description ?? todo.content,
        startedAt: Date.now(),
      };
    }

    if (event.type === "task_running") {
      return {
        ...todo,
        status: "in_progress" as const,
        latest_message: event.message,
        stream_messages: mergeStreamingMessages(
          todo.stream_messages,
          [event.message],
        ),
      };
    }

    if (event.type === "task_completed") {
      return {
        ...todo,
        status: "completed" as const,
        result: event.result,
        result_summary: event.summary ?? event.result ?? todo.result_summary,
        structured_summary: event.summary ?? todo.structured_summary,
        structured_findings: event.findings ?? todo.structured_findings,
        structured_citations: event.citations ?? todo.structured_citations,
        structured_gaps: event.open_questions ?? todo.structured_gaps,
        executionTimeSeconds: event.execution_time_seconds ?? (todo.startedAt ? (Date.now() - todo.startedAt) / 1000 : undefined),
      };
    }

    return {
      ...todo,
      status: "failed" as const,
      error: event.error ?? todo.error,
      executionTimeSeconds: event.execution_time_seconds ?? (todo.startedAt ? (Date.now() - todo.startedAt) / 1000 : undefined),
    };
  });

  return changed ? nextTodos : todos;
}

export default function ChatPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const { thread_id: threadIdFromPath } = useParams<{ thread_id: string }>();
  const isNewThread = threadIdFromPath === "new";
  const {
    data: session,
    isPending: isSessionPending,
    error: sessionError,
  } = authClient.useSession();
  const shouldKeepContentDuringAccessCheck = useMemo(() => {
    if (isNewThread) {
      return false;
    }

    return readThreadRouteHandoff()?.threadId === threadIdFromPath;
  }, [isNewThread, threadIdFromPath]);
  const [selectedMaterials] = useState<SelectedMaterial[]>(() =>
    parseSelectedMaterials(searchParams.get("materials"), searchParams.get("materials_key")),
  );
  const selectedMaterialScopes = useMemo(
    () =>
      Array.from(
        new Set(
          selectedMaterials
            .map((item) => item.scope ?? "global")
            .filter(
              (scope): scope is "global" | "thread" | "user" =>
                scope === "global" || scope === "thread" || scope === "user",
            ),
        ),
      ),
    [selectedMaterials],
  );

  const accessQuery = useQuery({
    queryKey: ["thread", "access", threadIdFromPath, session?.user.id],
    enabled:
      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ||
      (Boolean(session?.user.id) && !isSessionPending && !isNewThread),
    queryFn: async () => {
      const thread =
        await getAPIClient().threads.get<AgentThreadState>(threadIdFromPath);
      queryClient.setQueryData(
        ["thread", "details", threadIdFromPath, session?.user.id],
        thread,
      );
      const ownerId =
        typeof thread.metadata?.user_id === "string"
          ? thread.metadata.user_id
          : undefined;

      if (!ownerId && session?.user.id) {
        await getAPIClient().threads.update(threadIdFromPath, {
          metadata: {
            ...thread.metadata,
            user_id: session.user.id,
          },
        });
        return true;
      }

      return ownerId === session?.user.id;
    },
    retry: false,
    staleTime: 30_000,
  });

  useEffect(() => {
    if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
      return;
    }

    if (!isSessionPending && (!session || sessionError)) {
      const next = `/workspace/chats/${threadIdFromPath}`;
      void router.replace(`/auth?next=${encodeURIComponent(next)}`);
      router.refresh();
    }
  }, [
    isSessionPending,
    router,
    session,
    sessionError,
    threadIdFromPath,
  ]);

  useEffect(() => {
    if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" || isNewThread) {
      return;
    }

    if (accessQuery.data === false || accessQuery.isError) {
      void router.replace("/workspace/chats");
    }
  }, [accessQuery.data, accessQuery.isError, isNewThread, router]);

  useEffect(() => {
    if (!shouldKeepContentDuringAccessCheck) {
      return;
    }

    if (accessQuery.data !== undefined || accessQuery.isError) {
      clearThreadRouteHandoff(threadIdFromPath);
    }
  }, [
    accessQuery.data,
    accessQuery.isError,
    shouldKeepContentDuringAccessCheck,
    threadIdFromPath,
  ]);

  if (
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" &&
    !isNewThread &&
    ((isSessionPending && !sessionError) ||
      !session ||
      (!shouldKeepContentDuringAccessCheck && accessQuery.isPending) ||
      accessQuery.data === false)
  ) {
    return null;
  }

  return (
    <ChatPageContent
      initialThreadIdFromPath={threadIdFromPath}
      selectedMaterials={selectedMaterials}
      selectedMaterialScopes={selectedMaterialScopes}
    />
  );
}

function ChatPageContent({
  initialThreadIdFromPath,
  selectedMaterials,
  selectedMaterialScopes,
}: {
  initialThreadIdFromPath: string;
  selectedMaterials: SelectedMaterial[];
  selectedMaterialScopes: Array<"global" | "thread" | "user">;
}) {
  const { t } = useI18n();
  const router = useRouter();
  const apiClient = getAPIClient();
  const { data: session } = authClient.useSession();
  const [settings, setSettings] = useLocalSettings();
  const { models } = useModels();
  const { setOpen: setSidebarOpen } = useSidebar();
  const {
    artifacts,
    open: artifactsOpen,
    setOpen: setArtifactsOpen,
    setArtifacts,
    select: selectArtifact,
    selectedArtifact,
  } = useArtifacts();
  const searchParams = useSearchParams();
  const promptInputController = usePromptInputController();
  const didNavigateForCreatedRunRef = useRef(false);
  const activeRunRef = useRef<ActiveRun | null>(null);
  const inputInitialValue = useMemo(() => {
    if (
      initialThreadIdFromPath !== "new" ||
      searchParams.get("mode") !== "skill"
    ) {
      return undefined;
    }
    return t.inputBox.createSkillPrompt;
  }, [initialThreadIdFromPath, searchParams, t.inputBox.createSkillPrompt]);
  const lastInitialValueRef = useRef<string | undefined>(undefined);
  const setInputRef = useRef(promptInputController.textInput.setInput);
  setInputRef.current = promptInputController.textInput.setInput;
  useEffect(() => {
    if (
      inputInitialValue &&
      inputInitialValue !== lastInitialValueRef.current
    ) {
      lastInitialValueRef.current = inputInitialValue;
      setTimeout(() => {
        setInputRef.current(inputInitialValue);
        const textarea = document.querySelector("textarea");
        if (textarea) {
          textarea.focus();
          textarea.selectionStart = textarea.value.length;
          textarea.selectionEnd = textarea.value.length;
        }
      }, 100);
    }
  }, [inputInitialValue]);
  const isNewThread = useMemo(
    () => initialThreadIdFromPath === "new",
    [initialThreadIdFromPath],
  );
  const initialRouteHandoff = useMemo(() => {
    if (initialThreadIdFromPath === "new") {
      return null;
    }

    const handoff = readThreadRouteHandoff();
    return handoff?.threadId === initialThreadIdFromPath ? handoff : null;
  }, [initialThreadIdFromPath]);
  const [threadId, setThreadId] = useState<string | null>(null);
  useEffect(() => {
    if (initialThreadIdFromPath !== "new") {
      setThreadId(initialThreadIdFromPath);
    } else {
      setThreadId(uuid());
    }
  }, [initialThreadIdFromPath]);

  const { showNotification } = useNotification();
  const threadDetailsQuery = useQuery({
    queryKey: ["thread", "details", threadId, session?.user.id],
    enabled:
      !!threadId &&
      !isNewThread &&
      (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" || !!session?.user.id),
    queryFn: async () => apiClient.threads.get<AgentThreadState>(threadId!),
    staleTime: 30_000,
  });
  const [finalState, setFinalState] = useState<AgentThreadState | null>(null);
  const threadMetadataContext = useMemo(
    () => readThreadDisplayMetadata(threadDetailsQuery.data?.metadata),
    [threadDetailsQuery.data?.metadata],
  );
  const persistedContext = useMemo(
    () => threadMetadataContext ?? initialRouteHandoff?.context ?? null,
    [initialRouteHandoff?.context, threadMetadataContext],
  );
  const baseContext = useMemo(
    () => ({
      ...settings.context,
      ...persistedContext,
    }),
    [persistedContext, settings.context],
  );
  const updateSubtask = useUpdateSubtask();
  const streamStartTimeRef = useRef<number | null>(null);
  const [runElapsedSeconds, setRunElapsedSeconds] = useState<number | null>(null);
  const [liveTodos, setLiveTodos] = useState<Todo[] | null>(null);
  const [selectedTodoId, setSelectedTodoId] = useState<string | null>(null);
  const [selectedTodoDraft, setSelectedTodoDraft] = useState<Todo | null>(null);
  const selectTodo = useCallback((todo: Todo | null) => {
    if (!todo) {
      setSelectedTodoId(null);
      setSelectedTodoDraft(null);
      return;
    }

    setSelectedTodoDraft(todo);
    setSelectedTodoId(todo.id ?? todo.task_id ?? null);
  }, []);
  const thread = useThreadStream({
    isNewThread,
    threadId,
    onCreated(run) {
      activeRunRef.current = {
        runId: run.run_id,
        threadId: run.thread_id,
      };
      if (!isNewThread || didNavigateForCreatedRunRef.current) {
        return;
      }
      didNavigateForCreatedRunRef.current = true;
      rememberThreadRouteHandoff(run.thread_id, resolvedContext);
      if (
        env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true" &&
        session?.user.id
      ) {
        void apiClient
          .threads
          .update(run.thread_id, {
            metadata: {
              user_id: session.user.id,
              ...buildThreadDisplayMetadata(resolvedContext),
            },
          })
          .catch((error) => {
            console.error("Failed to persist thread display context:", error);
          });
      }
      const currentQuery = searchParams.toString();
      router.push(
        currentQuery
          ? `${pathOfThread(run.thread_id)}?${currentQuery}`
          : pathOfThread(run.thread_id),
      );
    },
    onFinish: (state) => {
      activeRunRef.current = null;
      setLiveTodos((currentLiveTodos) => {
        const stateTodos = state.todos ?? null;
        if (!stateTodos || !currentLiveTodos) return stateTodos;
        return stateTodos.map((todo) => {
          const live = currentLiveTodos.find((t) => todosMatch(t, todo));
          if (!live) return todo;
          return {
            ...todo,
            execution_time_seconds: todo.execution_time_seconds ?? live.execution_time_seconds,
            executionTimeSeconds: todo.executionTimeSeconds ?? live.executionTimeSeconds,
            startedAt: todo.startedAt ?? live.startedAt,
          };
        });
      });
      setFinalState(state);
      if (document.hidden || !document.hasFocus()) {
        let body = "Conversation finished";
        const lastMessage = state.messages[state.messages.length - 1];
        if (lastMessage) {
          const textContent = textOfMessage(lastMessage);
          if (textContent) {
            if (textContent.length > 200) {
              body = textContent.substring(0, 200) + "...";
            } else {
              body = textContent;
            }
          }
        }
        showNotification(state.title, {
          body,
        });
      }
    },
    onCustomEvent: (event) => {
      if (isTodoBoardUpdatedEvent(event)) {
        setLiveTodos((currentTodos) => {
          const eventTodos = event.todos;
          if (!currentTodos || currentTodos.length === 0) {
            return eventTodos;
          }

          return eventTodos.map((todo) => {
            const currentTodo =
              currentTodos.find((candidate) => todosMatch(candidate, todo)) ??
              null;
            if (!currentTodo) {
              return todo;
            }

            const merged = {
              ...currentTodo,
              ...todo,
              stream_messages: todo.stream_messages ?? currentTodo.stream_messages,
              latest_message: todo.latest_message ?? currentTodo.latest_message,
              result: todo.result ?? currentTodo.result,
              structured_summary:
                todo.structured_summary ?? currentTodo.structured_summary,
              structured_findings:
                todo.structured_findings ?? currentTodo.structured_findings,
              structured_citations:
                todo.structured_citations ?? currentTodo.structured_citations,
              structured_gaps:
                todo.structured_gaps ?? currentTodo.structured_gaps,
              task_description:
                todo.task_description ?? currentTodo.task_description,
            };
            // Track timing for main todos (no delegated task_id) via status transitions
            if (!todo.task_id) {
              if (todo.status === "in_progress" && currentTodo.status !== "in_progress") {
                merged.startedAt = Date.now();
              } else {
                merged.startedAt = currentTodo.startedAt;
              }
              if ((todo.status === "completed" || todo.status === "failed") && currentTodo.startedAt && !currentTodo.executionTimeSeconds) {
                merged.executionTimeSeconds = (Date.now() - currentTodo.startedAt) / 1000;
              } else {
                merged.executionTimeSeconds = currentTodo.executionTimeSeconds ?? merged.executionTimeSeconds;
              }
            }
            return merged;
          });
        });
        if (event.todos.length > 0) {
          setTodoListCollapsed(false);
        }
        return;
      }

      if (isTaskStartedEvent(event)) {
        setLiveTodos((currentTodos) =>
          mergeTaskEventIntoTodos(currentTodos, event),
        );
        return;
      }

      if (isTaskRunningEvent(event)) {
        setLiveTodos((currentTodos) =>
          mergeTaskEventIntoTodos(currentTodos, event),
        );
        return;
      }

      if (isTaskCompletedEvent(event)) {
        setLiveTodos((currentTodos) =>
          mergeTaskEventIntoTodos(currentTodos, event),
        );
        return;
      }

      if (isTaskFailedEvent(event)) {
        setLiveTodos((currentTodos) =>
          mergeTaskEventIntoTodos(currentTodos, event),
        );
      }
    },
  }) as unknown as UseStream<AgentThreadState>;
  useEffect(() => {
    if (thread.isLoading) setFinalState(null);
  }, [thread.isLoading]);

  useEffect(() => {
    if (thread.isLoading) {
      streamStartTimeRef.current = Date.now();
      setRunElapsedSeconds(null);
    } else if (streamStartTimeRef.current != null) {
      setRunElapsedSeconds((Date.now() - streamStartTimeRef.current) / 1000);
      streamStartTimeRef.current = null;
    }
  }, [thread.isLoading]);

  const title = useMemo(() => {
    let result = isNewThread
      ? ""
      : titleOfThread(thread as unknown as AgentThread);
    if (result === "Untitled") {
      result = "";
    }
    return result;
  }, [thread, isNewThread]);

  useEffect(() => {
    const pageTitle = isNewThread
      ? t.pages.newChat
      : thread.values?.title && thread.values.title !== "Untitled"
        ? thread.values.title
        : t.pages.untitled;
    if (thread.isThreadLoading) {
      document.title = `Loading... - ${t.pages.appName}`;
    } else {
      document.title = `${pageTitle} - ${t.pages.appName}`;
    }
  }, [
    isNewThread,
    t.pages.newChat,
    t.pages.untitled,
    t.pages.appName,
    thread.values.title,
    thread.isThreadLoading,
  ]);

  const [autoSelectFirstArtifact, setAutoSelectFirstArtifact] = useState(true);
  const [artifactCompareOpen, setArtifactCompareOpen] = useState(false);
  useEffect(() => {
    setArtifacts(thread.values.artifacts);
    if (
      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" &&
      autoSelectFirstArtifact
    ) {
      if (thread?.values?.artifacts?.length > 0) {
        setAutoSelectFirstArtifact(false);
        selectArtifact(thread.values.artifacts[0]!);
      }
    }
  }, [
    autoSelectFirstArtifact,
    selectArtifact,
    setArtifacts,
    thread.values.artifacts,
  ]);

  const artifactPanelOpen = useMemo(() => {
    if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
      return artifactsOpen && artifacts?.length > 0;
    }
    return artifactsOpen;
  }, [artifactsOpen, artifacts]);

  const handleKnowledgeCompareToggle = useCallback((open: boolean) => {
    setArtifactCompareOpen(open);
  }, []);

  useEffect(() => {
    if (!artifactPanelOpen) {
      setArtifactCompareOpen(false);
    }
  }, [artifactPanelOpen]);

  const [todoListCollapsed, setTodoListCollapsed] = useState(false);
  const displayedTodos = useMemo(
    () => liveTodos ?? thread.values.todos ?? [],
    [liveTodos, thread.values.todos],
  );
  const hasActiveTodos = useMemo(
    () =>
      displayedTodos.some(
        (todo) => todo.status === "pending" || todo.status === "in_progress",
      ),
    [displayedTodos],
  );

  const selectedTodo = useMemo(() => {
    const selectedById = selectedTodoId
      ? displayedTodos.find(
          (todo) => (todo.id ?? todo.task_id ?? null) === selectedTodoId,
        ) ?? null
      : null;

    if (selectedById) {
      return selectedById;
    }

    if (!selectedTodoDraft) {
      return null;
    }

    return (
      displayedTodos.find((todo) => {
        return todosMatch(selectedTodoDraft, todo);
      }) ?? selectedTodoDraft
    );
  }, [displayedTodos, selectedTodoDraft, selectedTodoId]);

  useEffect(() => {
    if (!selectedTodoDraft && !selectedTodoId) {
      return;
    }

    const matchedTodo = displayedTodos.find((todo) => {
      if (selectedTodoId && (todo.id ?? todo.task_id ?? null) === selectedTodoId) {
        return true;
      }

      if (!selectedTodoDraft) {
        return false;
      }

      return todosMatch(selectedTodoDraft, todo);
    });

    if (matchedTodo) {
      setSelectedTodoDraft(matchedTodo);
      if (!selectedTodoId && (matchedTodo.id ?? matchedTodo.task_id ?? null)) {
        setSelectedTodoId(matchedTodo.id ?? matchedTodo.task_id ?? null);
      }
    }
  }, [displayedTodos, selectedTodoDraft, selectedTodoId]);

  useEffect(() => {
    if (displayedTodos.length > 0 && hasActiveTodos) {
      setTodoListCollapsed(false);
    }
  }, [displayedTodos.length, hasActiveTodos]);

  useEffect(() => {
    if (typeof window === "undefined") {
      return;
    }

    const handleTodoSelected = (event: Event) => {
      const { detail } = event as CustomEvent<TodoSelectionDetail>;
      selectTodo(detail.todo);
      setTodoListCollapsed(false);
    };

    window.addEventListener(
      WORKSPACE_TODO_SELECTED_EVENT,
      handleTodoSelected as EventListener,
    );

    return () => {
      window.removeEventListener(
        WORKSPACE_TODO_SELECTED_EVENT,
        handleTodoSelected as EventListener,
      );
    };
  }, [selectTodo]);

  const resolvedModelName = useMemo(() => {
    if (models.length === 0) {
      return baseContext.model_name;
    }

    return (
      models.find((model) => model.name === baseContext.model_name)?.name ??
      models[0]?.name
    );
  }, [baseContext.model_name, models]);

  const resolvedContext = useMemo(
    () => ({
      ...baseContext,
      model_name: resolvedModelName,
    }),
    [baseContext, resolvedModelName],
  );

  const threadContext = useMemo(
    () => ({
      model_name: resolvedContext.model_name,
      thinking_enabled:
        resolvedContext.scenario === "research" ||
        (resolvedContext.scenario === "qa" && resolvedContext.tier === "pro"),
      is_plan_mode: resolvedContext.scenario === "research",
      max_concurrent_subagents: 4,
      subagent_enabled: true,
      qa_mode: resolvedContext.scenario === "qa",
      concise_answers:
        resolvedContext.scenario === "qa" && resolvedContext.tier === "ultra",
      selected_doc_ids: selectedMaterials.map((item) => item.doc_id),
      selected_sources_scope: selectedMaterialScopes,
      selected_materials: selectedMaterials,
    }),
    [resolvedContext, selectedMaterialScopes, selectedMaterials],
  );

  useEffect(() => {
    if (persistedContext) {
      return;
    }
    if (
      resolvedModelName &&
      settings.context.model_name !== resolvedModelName
    ) {
      setSettings("context", {
        model_name: resolvedModelName,
      });
    }
  }, [
    persistedContext,
    resolvedModelName,
    setSettings,
    settings.context.model_name,
  ]);

  const submitThread = useSubmitThread({
    isNewThread,
    threadId,
    thread,
    threadContext,
    displayContext: resolvedContext,
  });
  const handleSubmit = useCallback(
    async (...args: Parameters<typeof submitThread>) => {
      setLiveTodos(null);
      await submitThread(...args);
    },
    [submitThread],
  );
  const handleStop = useCallback(async () => {
    const activeRun = activeRunRef.current;
    const currentThreadId = activeRun?.threadId ?? threadId;
    const currentRunId =
      activeRun?.runId ?? readActiveRunId(activeRun?.threadId ?? threadId);

    clearActiveRunId(currentThreadId);

    const stopPromise = thread.stop();
    try {
      if (currentThreadId) {
        await getAPIClient().threads.updateState(currentThreadId, {
          values: {
            subtasks_cancel_requested_at: new Date().toISOString(),
          },
        });
      }
    } catch (error) {
      console.error("Failed to mark subtasks for cancellation:", error);
    }

    try {
      if (currentThreadId && currentRunId) {
        await getAPIClient().runs.cancel(
          currentThreadId,
          currentRunId,
          true,
        );
      }
    } catch (error) {
      console.error("Failed to cancel active run:", error);
    } finally {
      activeRunRef.current = null;
      await stopPromise;
    }
  }, [thread, threadId]);

  const handleSelectTodo = useCallback((todo: Todo) => {
    selectTodo(todo);
    setTodoListCollapsed(false);
  }, [selectTodo]);

  const injectMockCitationFlow = useCallback(() => {
    const MOCK_CITATION_REGISTRY = [
      {
        id: "1",
        label: "《张之洞全集·公牍·咨札》第五册，第10页",
        url: "/api/knowledge/docs/张之洞全集.pdf?page_no=10&pdf_page_no=10",
      },
      {
        id: "2",
        label: "《近代中国经济政策演变史稿》第45页",
        url: "/api/knowledge/docs/近代中国经济政策演变史稿.pdf?page_no=45&pdf_page_no=45",
      },
      {
        id: "5",
        label: "《张之洞全集·公牍·咨札》第六册，第88页",
        url: "/api/knowledge/docs/张之洞全集.pdf?page_no=88&pdf_page_no=88",
      },
      {
        id: "9",
        label: "《湖北枪炮厂档案》光绪二十二年",
        url: "/api/knowledge/docs/湖北枪炮厂档案.pdf?page_no=5&pdf_page_no=5",
      },
      {
        id: "30",
        label: "《粤汉铁路史》第120页",
        url: "/api/knowledge/docs/粤汉铁路史.pdf?page_no=120&pdf_page_no=120",
      },
    ];

    const mockTodoId = "mock-todo-1";
    const mockTaskId = "mock-task-1";

    const mockSubtaskResult = `## 任务结果
本任务围绕张之洞在洋务运动与实业建设中的具体贡献展开系统检索，以《张之洞全集》公牍·咨札（第五册光绪八年至二十二年、第六册光绪二十三年至三十三年）与《近代中国经济政策演变史稿》为核心来源，系统梳理出张之洞创办或推动的企业、矿务、铁路等完整时间线与关键制度措施。

## 关键发现
- 张之洞在光绪十六年（1890）调任湖广总督后即启动湖北近代工业化，优先布局汉阳铁厂、大冶铁矿及荆当煤务，形成完整的钢铁工业链[citation:1]
- 汉阳铁厂于光绪二十二年（1896）正式招商，由盛宣怀督办、郑观应总办，完成从官办到官商合办的转型[citation:1]
- 湖北枪炮厂于光绪二十二年首次出现在公牍中，刘祖桂为首任提调，钱守恂继任；光绪二十四年派人赴北洋考察学习先进军火制造技术[citation:1][citation:9]
- 布局（纺织局）于光绪十八年（1892）由赵毓楠担任总监工，光绪十九年获拨款七八万两扩建，光绪二十三年改为官办[citation:1][citation:2]
- 张之洞系统勘查大冶铁山、萍乡煤矿、荆当煤务、兴国州鑛铁、竹山铜矿、蕲水煤矿等资源，构建资源支撑体系[citation:1][citation:5]
- 铁路方面，张之洞主持芦汉铁路勘线，推动汉口至保定铁路走向；主导粤汉铁路赎回，以美金六百七十万元收回商办，为近代中国收回利权的重要标志[citation:1][citation:2][citation:30]

## 关键引文
- [citation:1]
- [citation:2]
- [citation:5]
- [citation:9]
- [citation:30]

## 未解决缺口
- 张之洞全集电牍部分（第十册光绪二十五年至二十八年）仅完成了目录页的检索，涉及铁路、企业、电报的具体电文内容尚未详细展开阅读
- 汉阳铁厂创办章程的具体条款、招商合同详细文本尚未逐条展开`;

    const mockTodo: Todo = {
      id: mockTodoId,
      content: "检索张之洞在洋务运动与实业建设中的具体贡献",
      status: "completed",
      task_id: mockTaskId,
      subagent_type: "general-purpose",
      result: mockSubtaskResult,
      result_summary:
        "梳理张之洞创办的企业、矿务、铁路时间线与关键制度措施",
      structured_summary: mockSubtaskResult.split("## 关键发现")[0]?.trim() ?? "",
      structured_findings: [
        "张之洞在光绪十六年（1890）调任湖广总督后即启动湖北近代工业化，优先布局汉阳铁厂、大冶铁矿及荆当煤务，形成完整的钢铁工业链[citation:1]",
        "汉阳铁厂于光绪二十二年（1896）正式招商，由盛宣怀督办、郑观应总办，完成从官办到官商合办的转型[citation:1]",
        "湖北枪炮厂于光绪二十二年首次出现在公牍中，刘祖桂为首任提调，钱守恂继任；光绪二十四年派人赴北洋考察学习先进军火制造技术[citation:1][citation:9]",
        "布局（纺织局）于光绪十八年（1892）由赵毓楠担任总监工，光绪十九年获拨款七八万两扩建，光绪二十三年改为官办[citation:1][citation:2]",
        "张之洞系统勘查大冶铁山、萍乡煤矿、荆当煤务、兴国州鑛铁、竹山铜矿、蕲水煤矿等资源，构建资源支撑体系[citation:1][citation:5]",
        "铁路方面，张之洞主持芦汉铁路勘线，推动汉口至保定铁路走向；主导粤汉铁路赎回，以美金六百七十万元收回商办，为近代中国收回利权的重要标志[citation:1][citation:2][citation:30]",
      ],
      structured_citations: [
        "[citation:1]",
        "[citation:2]",
        "[citation:5]",
        "[citation:9]",
        "[citation:30]",
      ],
      structured_gaps: [
        "张之洞全集电牍部分（第十册光绪二十五年至二十八年）仅完成了目录页的检索，涉及铁路、企业、电报的具体电文内容尚未详细展开阅读",
        "汉阳铁厂创办章程的具体条款、招商合同详细文本尚未逐条展开",
      ],
      citation_registry: MOCK_CITATION_REGISTRY,
    };

    // 1. 注入子任务
    updateSubtask({
      id: mockTaskId,
      status: "completed",
      description: "检索张之洞在洋务运动与实业建设中的具体贡献",
      result: mockSubtaskResult,
      summary: mockTodo.structured_summary,
      findings: mockTodo.structured_findings,
      citations: mockTodo.structured_citations,
      openQuestions: mockTodo.structured_gaps,
    });

    // 2. 注入 todo board
    setLiveTodos((prev) => {
      const next = prev ? prev.filter((t) => t.id !== mockTodoId) : [];
      return [...next, mockTodo];
    });

    // 3. 注入最终状态（让 MessageList 通过 override 显示）
    const mockMessages = [
      {
        type: "human",
        id: "mock-human-1",
        content: "请帮我检索张之洞在洋务运动与实业建设中的具体贡献",
      },
      {
        type: "ai",
        id: "mock-ai-1",
        content: "我来帮你分步骤检索这个问题。",
        tool_calls: [
          {
            id: "mock-tool-call-1",
            name: "write_todos",
            args: {
              todos: [
                {
                  id: mockTodoId,
                  content:
                    "检索张之洞在洋务运动与实业建设中的具体贡献",
                  status: "in_progress",
                },
              ],
            },
          },
        ],
      },
      {
        type: "tool",
        id: "mock-tool-1",
        tool_call_id: "mock-tool-call-1",
        content: "Updated todo board.\nCurrent todos:\n- [in_progress] 检索张之洞在洋务运动与实业建设中的具体贡献",
      },
      {
        type: "ai",
        id: "mock-ai-final",
        content: `根据检索结果，张之洞在湖广总督任内推动了多项实业建设[citation:1]。

具体包括：
- 汉阳铁厂于光绪二十二年正式招商，由盛宣怀督办、郑观应总办[citation:1]
- 系统勘查大冶铁山、萍乡煤矿、荆当煤务等资源，构建资源支撑体系[citation:1][citation:5]
- 布局（纺织局）于光绪十八年（1892）由赵毓楠担任总监工[citation:1][citation:2]

铁路方面，张之洞主持芦汉铁路勘线，推动汉口至保定铁路走向；主导粤汉铁路赎回，以美金六百七十万元收回商办[citation:1][citation:2][citation:30]。

参考文献
1. [citation:1]
2. [citation:2]
3. [citation:5]
4. [citation:9]
5. [citation:30]

建议问题
1. 张之洞在汉阳铁厂招商过程中与盛宣怀的具体分工是什么？
2. 湖北枪炮厂的技术引进细节还有哪些可以补充？
3. 粤汉铁路赎回过程中遇到了哪些阻力？`,
      },
    ];

    setFinalState({
      messages: mockMessages as unknown as AgentThreadState["messages"],
      knowledge_citation_registry: MOCK_CITATION_REGISTRY,
      todos: [mockTodo],
      title: "Mock: 张之洞洋务运动检索",
    } as AgentThreadState);

    console.info("[MockCitationFlow] Injected mock data", {
      registryCount: MOCK_CITATION_REGISTRY.length,
      todoId: mockTodoId,
      taskId: mockTaskId,
    });
  }, [updateSubtask, setLiveTodos, setFinalState]);

  if (!threadId) {
    return null;
  }

  return (
    <ThreadContext.Provider value={{ threadId, thread }}>
      <div className="flex size-full min-h-0">
        <div className="relative min-w-0 flex-1">
          <div className="relative flex size-full min-h-0 justify-between">
            <header
              className={cn(
                "absolute top-0 right-0 left-0 z-30 flex h-14 shrink-0 items-center px-4",
                isNewThread
                  ? "bg-background/0 backdrop-blur-none"
                  : "bg-background/80 shadow-xs backdrop-blur",
              )}
            >
              <div className="flex w-full items-center text-sm font-medium">
                {title !== "Untitled" && (
                  <ThreadTitle threadId={threadId} threadTitle={title} />
                )}
              </div>
              <div className="flex items-center gap-2">
                {process.env.NODE_ENV === "development" && (
                  <Button
                    variant="outline"
                    size="sm"
                    className="text-xs"
                    onClick={injectMockCitationFlow}
                  >
                    Mock Citation
                  </Button>
                )}
                {artifacts?.length > 0 && !artifactsOpen && (
                  <Tooltip content="Show artifacts of this conversation">
                    <Button
                      className="text-muted-foreground hover:text-foreground"
                      variant="ghost"
                      onClick={() => {
                        setArtifactsOpen(true);
                        setSidebarOpen(false);
                      }}
                    >
                      <FilesIcon />
                      {t.common.artifacts}
                    </Button>
                  </Tooltip>
                )}
              </div>
            </header>
            <main className="relative flex min-h-0 max-w-full grow flex-col">
              <div className="flex size-full justify-center">
                  <MessageList
                    className={cn("size-full", !isNewThread && "pt-14")}
                    threadId={threadId}
                    thread={thread}
                    messagesOverride={
                      !thread.isLoading && finalState?.messages
                        ? (finalState.messages as Message[])
                        : undefined
                    }
                    citationRegistryOverride={
                      !thread.isLoading && finalState?.knowledge_citation_registry
                        ? finalState.knowledge_citation_registry
                        : undefined
                    }
                    paddingBottom={todoListCollapsed ? 140 : 400}
                    runElapsedSeconds={!thread.isLoading ? runElapsedSeconds ?? undefined : undefined}
                  />
                </div>
                <div className="absolute right-0 bottom-0 left-0 z-30 flex justify-center px-4">
                  <div
                    className={cn(
                      "relative w-full mb-4",
                      isNewThread && "-translate-y-[calc(50vh-96px)]",
                      isNewThread
                        ? "max-w-(--container-width-sm)"
                        : "max-w-(--container-width-md)",
                    )}
                  >
                    <div className="absolute bottom-full right-0 left-0 mb-1 z-0">
                      <TodoList
                        todos={displayedTodos}
                        collapsed={todoListCollapsed}
                        selectedTodoId={selectedTodoId}
                        hidden={displayedTodos.length === 0}
                        onSelectTodo={handleSelectTodo}
                        onToggle={() =>
                          setTodoListCollapsed(!todoListCollapsed)
                        }
                      />
                    </div>
                    <InputBox
                      className={cn("w-full shadow-2xl")}
                    isNewThread={isNewThread}
                    autoFocus={isNewThread}
                    status={thread.isLoading ? "streaming" : "ready"}
                    context={resolvedContext}
                    threadId={threadId}
                    selectedMaterials={selectedMaterials}
                    extraHeader={
                      isNewThread && (
                        <Welcome
                          scenario={resolvedContext.scenario}
                          tier={resolvedContext.tier}
                        />
                      )
                    }
                    disabled={env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true"}
                    onContextChange={(context) =>
                      setSettings("context", context)
                    }
                    onSubmit={handleSubmit}
                    onStop={handleStop}
                  />
                  {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" && (
                    <div className="text-muted-foreground/67 w-full translate-y-12 text-center text-xs">
                      {t.common.notAvailableInDemoMode}
                    </div>
                  )}
                </div>
              </div>
              
              {isNewThread && <SilkRibbon />}
            </main>
          </div>
        </div>
        {artifactPanelOpen && (
          <div
            className="bg-background relative z-40 h-full shrink-0 border-l p-4"
            style={{
              width: artifactCompareOpen
                ? `min(${KNOWLEDGE_ARTIFACT_PANEL_EXPANDED_WIDTH}px, calc(100vw - 24px))`
                : `${KNOWLEDGE_ARTIFACT_PANEL_DEFAULT_WIDTH}px`,
            }}
          >
            {selectedArtifact ? (
              <ArtifactFileDetail
                className="size-full"
                filepath={selectedArtifact}
                threadId={threadId}
                onKnowledgeCompareToggle={handleKnowledgeCompareToggle}
              />
            ) : (
              <div className="relative flex size-full justify-center">
                <div className="absolute top-1 right-1 z-30">
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    onClick={() => {
                      setArtifactsOpen(false);
                    }}
                  >
                    <XIcon />
                  </Button>
                </div>
                {thread.values.artifacts?.length === 0 ? (
                  <ConversationEmptyState
                    icon={<FilesIcon />}
                    title="No artifact selected"
                    description="Select an artifact to view its details"
                  />
                ) : (
                  <div className="flex size-full max-w-(--container-width-sm) flex-col justify-center p-4 pt-8">
                    <header className="shrink-0">
                      <h2 className="text-lg font-medium">Artifacts</h2>
                    </header>
                    <main className="min-h-0 grow">
                      <ArtifactFileList
                        className="max-w-(--container-width-sm) p-4 pt-12"
                        files={thread.values.artifacts ?? []}
                        threadId={threadId}
                      />
                    </main>
                  </div>
                )}
              </div>
            )}
          </div>
        )}
        <SubtaskDetailSheet
          open={selectedTodo !== null}
          todo={selectedTodo}
          onOpenChange={(open) => {
            if (!open) {
              selectTodo(null);
            }
          }}
        />
      </div>
    </ThreadContext.Provider>
  );
}
