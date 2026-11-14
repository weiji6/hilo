import { createContext, useCallback, useContext, useState, type Dispatch, type SetStateAction } from "react";
import type { AIMessage } from "@langchain/langgraph-sdk";

import type { Subtask } from "./types";

export interface SubtaskContextValue {
  tasks: Record<string, Subtask>;
  setTasks: Dispatch<SetStateAction<Record<string, Subtask>>>;
}

export const SubtaskContext = createContext<SubtaskContextValue>({
  tasks: {},
  setTasks: () => {
    /* noop */
  },
});

export function SubtasksProvider({ children }: { children: React.ReactNode }) {
  const [tasks, setTasks] = useState<Record<string, Subtask>>({});
  return (
    <SubtaskContext.Provider value={{ tasks, setTasks }}>
      {children}
    </SubtaskContext.Provider>
  );
}

export function useSubtaskContext() {
  const context = useContext(SubtaskContext);
  if (context === undefined) {
    throw new Error(
      "useSubtaskContext must be used within a SubtaskContext.Provider",
    );
  }
  return context;
}

export function useSubtask(id: string) {
  const { tasks } = useSubtaskContext();
  return tasks[id];
}

function mergeMessageSnapshots(
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

export function useUpdateSubtask() {
  const { setTasks } = useSubtaskContext();
  const updateSubtask = useCallback(
    (task: Partial<Subtask> & { id: string }) => {
      setTasks((prevTasks) => {
        const previousTask = prevTasks[task.id];
        const nextTask = {
          ...previousTask,
          ...task,
        } as Subtask;

        if (task.messages && task.messages.length > 0) {
          nextTask.messages = mergeMessageSnapshots(
            previousTask?.messages,
            task.messages,
          );
        }

        return {
          ...prevTasks,
          [task.id]: nextTask,
        };
      });
    },
    [setTasks],
  );
  return updateSubtask;
}
