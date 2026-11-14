"use client";

import type { AgentScenario, AgentTier } from "@/core/settings/local";
import { useI18n } from "@/core/i18n/hooks";
import type { Translations } from "@/core/i18n/locales/types";

import { Tooltip } from "./tooltip";

type PresetLabelKey = keyof Pick<
  Translations["inputBox"],
  | "researchProLabel"
  | "researchUltraLabel"
  | "qaProLabel"
  | "qaUltraLabel"
>;

type PresetDescriptionKey = keyof Pick<
  Translations["inputBox"],
  | "researchProDescription"
  | "researchUltraDescription"
  | "qaProDescription"
  | "qaUltraDescription"
>;

function getPresetKeys(
  scenario: AgentScenario,
  tier: AgentTier,
): { label: PresetLabelKey; description: PresetDescriptionKey } {
  if (scenario === "research" && tier === "ultra") {
    return {
      label: "researchUltraLabel",
      description: "researchUltraDescription",
    };
  }
  if (scenario === "qa" && tier === "pro") {
    return { label: "qaProLabel", description: "qaProDescription" };
  }
  if (scenario === "qa" && tier === "ultra") {
    return { label: "qaUltraLabel", description: "qaUltraDescription" };
  }
  return { label: "researchProLabel", description: "researchProDescription" };
}

export function ModeHoverGuide({
  scenario,
  tier,
  children,
  showTitle = true,
}: {
  scenario: AgentScenario;
  tier: AgentTier;
  children: React.ReactNode;
  /** When true, tooltip shows "ModeName: Description". When false, only description. */
  showTitle?: boolean;
}) {
  const { t } = useI18n();
  const { label, description } = getPresetKeys(scenario, tier);
  const labelText = t.inputBox[label];
  const descriptionText = t.inputBox[description];
  const content = showTitle
    ? `${labelText}: ${descriptionText}`
    : descriptionText;

  return <Tooltip content={content}>{children}</Tooltip>;
}
