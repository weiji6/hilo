import type { Todo } from "./types";

export const WORKSPACE_TODO_SELECTED_EVENT = "workspace:todo-selected";

export interface TodoSelectionDetail {
  todo: Todo;
}

export function dispatchTodoSelected(detail: TodoSelectionDetail) {
  if (typeof window === "undefined") {
    return;
  }

  window.dispatchEvent(
    new CustomEvent<TodoSelectionDetail>(WORKSPACE_TODO_SELECTED_EVENT, {
      detail,
    }),
  );
}
