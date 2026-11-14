"use client";

import type { ChatStatus } from "ai";
import {
  CheckIcon,
  GraduationCapIcon,
  MessageCircleIcon,
  PaperclipIcon,
  PlusIcon,
  SparklesIcon,
  RocketIcon,
  ZapIcon,
} from "lucide-react";
import { useSearchParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useMemo,
  useState,
  type ComponentProps,
} from "react";

import {
  PromptInput,
  PromptInputActionMenu,
  PromptInputActionMenuContent,
  PromptInputActionMenuItem,
  PromptInputActionMenuTrigger,
  PromptInputAttachment,
  PromptInputAttachments,
  PromptInputBody,
  PromptInputButton,
  PromptInputFooter,
  PromptInputSubmit,
  PromptInputTools,
  usePromptInputAttachments,
  usePromptInputController,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { ConfettiButton } from "@/components/ui/confetti-button";
import {
  DropdownMenuGroup,
  DropdownMenuLabel,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import {
  buildMentionableKnowledgeMaterials,
  resolveSelectedMaterialsFromMentions,
} from "@/core/knowledge/mentions";
import { useKnowledgeFiles } from "@/core/knowledge/hooks";
import type { SelectedMaterial } from "@/core/knowledge/selection";
import { useUserKnowledgeRecords } from "@/core/knowledge/user-hooks";
import type { Translations } from "@/core/i18n/locales/types";
import { useModels } from "@/core/models/hooks";
import type { AgentScenario, AgentTier } from "@/core/settings/local";
import type { AgentThreadContext } from "@/core/threads";
import { useEagerUpload } from "@/core/uploads";
import { cn } from "@/lib/utils";

import {
  ModelSelector,
  ModelSelectorContent,
  ModelSelectorInput,
  ModelSelectorItem,
  ModelSelectorList,
  ModelSelectorName,
  ModelSelectorTrigger,
} from "../ai-elements/model-selector";
import { Suggestion, Suggestions } from "../ai-elements/suggestion";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "../ui/dropdown-menu";

import { ModeHoverGuide } from "./mode-hover-guide";
import { KnowledgeMentionTextarea } from "./knowledge-mention-textarea";
import { Tooltip } from "./tooltip";

type ContextShape = Omit<
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

function presetLabelKey(
  scenario: AgentScenario,
  tier: AgentTier,
): keyof Pick<
  Translations["inputBox"],
  "researchProLabel" | "researchUltraLabel" | "qaProLabel" | "qaUltraLabel"
> {
  if (scenario === "research" && tier === "ultra") {
    return "researchUltraLabel";
  }
  if (scenario === "qa" && tier === "pro") {
    return "qaProLabel";
  }
  if (scenario === "qa" && tier === "ultra") {
    return "qaUltraLabel";
  }
  return "researchProLabel";
}

function PresetIcon({
  scenario,
  tier,
}: {
  scenario: AgentScenario;
  tier: AgentTier;
}) {
  if (scenario === "research" && tier === "ultra") {
    return <RocketIcon className="size-3 text-primary" />;
  }
  if (scenario === "qa" && tier === "ultra") {
    return <ZapIcon className="size-3" />;
  }
  if (scenario === "qa" && tier === "pro") {
    return <MessageCircleIcon className="size-3" />;
  }
  return <GraduationCapIcon className="size-3" />;
}

export function InputBox({
  className,
  disabled,
  autoFocus,
  status = "ready",
  context,
  extraHeader,
  isNewThread,
  threadId,
  selectedMaterials = [],
  onContextChange,
  onSubmit,
  onStop,
  ...props
}: Omit<ComponentProps<typeof PromptInput>, "onSubmit"> & {
  assistantId?: string | null;
  status?: ChatStatus;
  disabled?: boolean;
  context: ContextShape;
  extraHeader?: React.ReactNode;
  isNewThread?: boolean;
  /** Thread ID used to eagerly upload attachments as soon as they are added. */
  threadId?: string | null;
  selectedMaterials?: SelectedMaterial[];
  onContextChange?: (context: ContextShape) => void;
  onSubmit?: (message: PromptInputMessage) => void;
  onStop?: () => void;
}) {
  const { t } = useI18n();
  const searchParams = useSearchParams();
  const [modelDialogOpen, setModelDialogOpen] = useState(false);
  const { models } = useModels();
  const knowledgeFilesQuery = useKnowledgeFiles();
  const userKnowledgeRecordsQuery = useUserKnowledgeRecords();

  const mentionables = useMemo(
    () =>
      buildMentionableKnowledgeMaterials(
        knowledgeFilesQuery.data?.files ?? [],
        userKnowledgeRecordsQuery.data?.records ?? [],
      ),
    [knowledgeFilesQuery.data?.files, userKnowledgeRecordsQuery.data?.records],
  );

  useEffect(() => {
    if (models.length === 0) {
      return;
    }
    const currentModel = models.find((m) => m.name === context.model_name);
    const fallbackModel = currentModel ?? models[0]!;
    const nextModelName = fallbackModel.name;
    if (context.model_name === nextModelName) {
      return;
    }
    onContextChange?.({
      ...context,
      model_name: nextModelName,
    });
  }, [context, models, onContextChange]);

  const selectedModel = useMemo(() => {
    if (models.length === 0) {
      return undefined;
    }
    return models.find((m) => m.name === context.model_name) ?? models[0];
  }, [context.model_name, models]);

  const handleModelSelect = useCallback(
    (model_name: string) => {
      const model = models.find((m) => m.name === model_name);
      if (!model) {
        return;
      }
      onContextChange?.({
        ...context,
        model_name,
      });
      setModelDialogOpen(false);
    },
    [onContextChange, context, models],
  );

  const handlePresetSelect = useCallback(
    (scenario: AgentScenario, tier: AgentTier) => {
      onContextChange?.({
        ...context,
        scenario,
        tier,
      });
    },
    [onContextChange, context],
  );

  const triggerLabel = useMemo(
    () => t.inputBox[presetLabelKey(context.scenario, context.tier)],
    [context.scenario, context.tier, t],
  );

  const isPreset = useCallback(
    (scenario: AgentScenario, tier: AgentTier) =>
      context.scenario === scenario && context.tier === tier,
    [context.scenario, context.tier],
  );
  // Eagerly upload files the moment they are added (drop or file-dialog).
  // This way files are already on the server by the time the user clicks send.
  const attachments = usePromptInputAttachments();
  const { isUploading } = useEagerUpload(threadId, attachments.files);

  const handleSubmit = useCallback(
    async (message: PromptInputMessage) => {
      if (status === "streaming") {
        onStop?.();
        return;
      }
      const { normalizedText, selectedMaterials } =
        resolveSelectedMaterialsFromMentions(message.text, mentionables);
      const nextText = normalizedText.trim() || message.text.trim();
      // Allow submission when files are attached even without text —
      // the backend will inject the file contents automatically.
      if (!nextText && message.files.length === 0) {
        return;
      }
      onSubmit?.({
        ...message,
        text: nextText,
        selectedMaterials:
          selectedMaterials.length > 0 ? selectedMaterials : undefined,
      });
    },
    [mentionables, onSubmit, onStop, status],
  );
  return (
    <PromptInput
      className={cn(
        "bg-[#fdfbf6] rounded-sm border-2 border-[#7e332e]/20 shadow-[4px_4px_0_rgba(126,51,46,0.05)] transition-all duration-300 ease-out *:data-[slot='input-group']:rounded-sm",
        className,
      )}
      disabled={disabled}
      globalDrop
      multiple
      onSubmit={handleSubmit}
      {...props}
    >
      {extraHeader && (
        <div className="absolute top-0 right-0 left-0 z-10">
          <div className="absolute right-0 bottom-0 left-0 flex items-center justify-center">
            {extraHeader}
          </div>
        </div>
      )}
      <PromptInputAttachments>
        {(attachment) => <PromptInputAttachment data={attachment} />}
      </PromptInputAttachments>
      <PromptInputBody className="z-3 w-full">
        <KnowledgeMentionTextarea
          autoFocus={autoFocus}
          className={cn("w-full font-serif text-stone-800 placeholder:text-stone-400 focus-visible:ring-primary/20")}
          disabled={disabled}
          mentionables={mentionables}
          placeholder={t.inputBox.placeholder}
          selectedMaterials={selectedMaterials}
        />
      </PromptInputBody>
      <PromptInputFooter className="flex">
        <PromptInputTools>
          {/* TODO: Add more connectors here
          <PromptInputActionMenu>
            <PromptInputActionMenuTrigger className="px-2!" />
            <PromptInputActionMenuContent>
              <PromptInputActionAddAttachments
                label={t.inputBox.addAttachments}
              />
            </PromptInputActionMenuContent>
          </PromptInputActionMenu> */}
          <AddAttachmentsButton className="px-2!" />
          {/* Mode Switcher Removed per scholarly redesign */}
            {/* Mode Menu Content Removed */}
        </PromptInputTools>
        <PromptInputTools>
          <ModelSelector
            open={modelDialogOpen}
            onOpenChange={setModelDialogOpen}
          >
            <ModelSelectorTrigger asChild>
              <PromptInputButton className="border-stone-200 bg-stone-50/50 hover:bg-stone-100 hover:text-primary transition-colors">
                <ModelSelectorName className="text-xs font-serif font-medium">
                  {selectedModel?.display_name}
                </ModelSelectorName>
              </PromptInputButton>
            </ModelSelectorTrigger>
            <ModelSelectorContent>
              <ModelSelectorInput placeholder={t.inputBox.searchModels} />
              <ModelSelectorList>
                {models.map((m) => (
                  <ModelSelectorItem
                    key={m.name}
                    value={m.name}
                    onSelect={() => handleModelSelect(m.name)}
                  >
                    <ModelSelectorName>{m.display_name}</ModelSelectorName>
                    {m.name === context.model_name ? (
                      <CheckIcon className="ml-auto size-4" />
                    ) : (
                      <div className="ml-auto size-4" />
                    )}
                  </ModelSelectorItem>
                ))}
              </ModelSelectorList>
            </ModelSelectorContent>
          </ModelSelector>
          <PromptInputSubmit
            className="rounded-sm bg-primary text-white hover:bg-primary/90 shadow-[2px_2px_0_rgba(126,51,46,0.2)] active:translate-x-0.5 active:translate-y-0.5 active:shadow-none transition-all"
            disabled={disabled || isUploading}
            variant="ghost" // Using ghost to ignore parent outline variants
            status={isUploading ? "submitted" : status}
          />
        </PromptInputTools>
      </PromptInputFooter>
      {/* Suggestions Removed per scholarly redesign */}
      {!isNewThread && (
        <div className="bg-background absolute right-0 -bottom-[17px] left-0 z-0 h-4"></div>
      )}
    </PromptInput>
  );
}

function SuggestionList() {
  const { t } = useI18n();
  const { textInput } = usePromptInputController();
  const handleSuggestionClick = useCallback(
    (prompt: string | undefined) => {
      if (!prompt) return;
      textInput.setInput(prompt);
      setTimeout(() => {
        const textarea = document.querySelector<HTMLTextAreaElement>(
          "textarea[name='message']",
        );
        if (textarea) {
          const selStart = prompt.indexOf("[");
          const selEnd = prompt.indexOf("]");
          if (selStart !== -1 && selEnd !== -1) {
            textarea.setSelectionRange(selStart, selEnd + 1);
            textarea.focus();
          }
        }
      }, 500);
    },
    [textInput],
  );
  return (
    <Suggestions className="min-h-16 w-fit items-start">
      <ConfettiButton
        className="text-muted-foreground cursor-pointer rounded-full px-4 text-xs font-normal"
        variant="outline"
        size="sm"
        onClick={() => handleSuggestionClick(t.inputBox.surpriseMePrompt)}
      >
        <SparklesIcon className="size-4" /> {t.inputBox.surpriseMe}
      </ConfettiButton>
      {t.inputBox.suggestions.map((suggestion) => (
        <Suggestion
          key={suggestion.suggestion}
          icon={suggestion.icon}
          suggestion={suggestion.suggestion}
          onClick={() => handleSuggestionClick(suggestion.prompt)}
        />
      ))}
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Suggestion icon={PlusIcon} suggestion={t.common.create} />
        </DropdownMenuTrigger>
        <DropdownMenuContent align="start">
          <DropdownMenuGroup>
            {t.inputBox.suggestionsCreate.map((suggestion, index) =>
              "type" in suggestion && suggestion.type === "separator" ? (
                <DropdownMenuSeparator key={index} />
              ) : (
                !("type" in suggestion) && (
                  <DropdownMenuItem
                    key={suggestion.suggestion}
                    onClick={() => handleSuggestionClick(suggestion.prompt)}
                  >
                    {suggestion.icon && <suggestion.icon className="size-4" />}
                    {suggestion.suggestion}
                  </DropdownMenuItem>
                )
              ),
            )}
          </DropdownMenuGroup>
        </DropdownMenuContent>
      </DropdownMenu>
    </Suggestions>
  );
}

function AddAttachmentsButton({ className }: { className?: string }) {
  const { t } = useI18n();
  const attachments = usePromptInputAttachments();
  return (
    <Tooltip content={t.inputBox.addAttachments}>
      <PromptInputButton
        className={cn(
          "px-2! border-stone-200 bg-stone-50/50 hover:bg-stone-100 hover:text-primary transition-colors",
          className,
        )}
        onClick={() => attachments.openFileDialog()}
      >
        <PaperclipIcon className="size-3" />
      </PromptInputButton>
    </Tooltip>
  );
}
