import type { AgentThreadContext } from "../threads";

export type AgentScenario = "research" | "qa";
export type AgentTier = "pro" | "ultra";

export const DEFAULT_LOCAL_SETTINGS: LocalSettings = {
  notification: {
    enabled: true,
  },
  context: {
    model_name: undefined,
    scenario: "research",
    tier: "pro",
  },
  layout: {
    sidebar_collapsed: false,
  },
};

const LOCAL_SETTINGS_KEY = "deerflow.local-settings";

export interface LocalSettings {
  notification: {
    enabled: boolean;
  };
  context: Omit<
    AgentThreadContext,
    | "thread_id"
    | "is_plan_mode"
    | "thinking_enabled"
    | "subagent_enabled"
    | "qa_mode"
    | "concise_answers"
  > & {
    scenario: AgentScenario;
    tier: AgentTier;
  };
  layout: {
    sidebar_collapsed: boolean;
  };
}

function migrateStoredContext(raw: unknown): LocalSettings["context"] {
  const base = { ...DEFAULT_LOCAL_SETTINGS.context };
  if (!raw || typeof raw !== "object") {
    return base;
  }
  const c = raw as Record<string, unknown>;
  const model_name =
    typeof c.model_name === "string" || c.model_name === undefined
      ? (c.model_name as string | undefined)
      : base.model_name;
  if (c.scenario === "research" || c.scenario === "qa") {
    const tier = c.tier === "ultra" ? "ultra" : "pro";
    return { model_name, scenario: c.scenario, tier };
  }
  const mode = c.mode as string | undefined;
  let scenario: AgentScenario = "research";
  let tier: AgentTier = "pro";
  if (mode === "flash" || mode === "thinking") {
    scenario = "qa";
    tier = mode === "flash" ? "ultra" : "pro";
  } else if (mode === "ultra") {
    scenario = "research";
    tier = "ultra";
  } else if (mode === "pro") {
    scenario = "research";
    tier = "pro";
  }
  return { model_name, scenario, tier };
}

export function getLocalSettings(): LocalSettings {
  if (typeof window === "undefined") {
    return DEFAULT_LOCAL_SETTINGS;
  }
  const json = localStorage.getItem(LOCAL_SETTINGS_KEY);
  try {
    if (json) {
      const settings = JSON.parse(json);
      const mergedSettings = {
        ...DEFAULT_LOCAL_SETTINGS,
        context: migrateStoredContext(settings.context),
        layout: {
          ...DEFAULT_LOCAL_SETTINGS.layout,
          ...settings.layout,
        },
        notification: {
          ...DEFAULT_LOCAL_SETTINGS.notification,
          ...settings.notification,
        },
      };
      return mergedSettings;
    }
  } catch {}
  return DEFAULT_LOCAL_SETTINGS;
}

export function saveLocalSettings(settings: LocalSettings) {
  localStorage.setItem(LOCAL_SETTINGS_KEY, JSON.stringify(settings));
}
