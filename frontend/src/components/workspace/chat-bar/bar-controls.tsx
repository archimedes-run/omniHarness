"use client";

import type { ChatStatus } from "ai";
import {
  ArrowRightIcon,
  CheckIcon,
  ChevronDownIcon,
  Loader2Icon,
  SquareIcon,
} from "lucide-react";

import {
  ModelSelector,
  ModelSelectorContent,
  ModelSelectorInput,
  ModelSelectorItem,
  ModelSelectorList,
  ModelSelectorName,
  ModelSelectorTrigger,
} from "@/components/ai-elements/model-selector";
import { PromptInputSubmit } from "@/components/ai-elements/prompt-input";
import { BrandLogo } from "@/components/brand";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useI18n } from "@/core/i18n/hooks";
import type { Model } from "@/core/models/types";
import { cn } from "@/lib/utils";

import { ModeHoverGuide } from "../mode-hover-guide";

import { modelProvider, type InputMode, type ReasoningEffort } from "./logic";

// Chat-Bar-v2.dc.html: 36 px, a muted label and a bright value.
export const PILL =
  "bg-surface-raised border-border text-foreground hover:border-border-strong focus-visible:ring-ring inline-flex h-9 items-center gap-1.5 rounded-[10px] border px-3 text-sm focus-visible:ring-2 focus-visible:outline-none disabled:opacity-50 max-sm:h-11";
const LABEL = "text-muted-foreground";

function useModeLabels() {
  const { t } = useI18n();
  return {
    flash: [t.inputBox.flashMode, t.inputBox.flashModeDescription],
    thinking: [t.inputBox.reasoningMode, t.inputBox.reasoningModeDescription],
    pro: [t.inputBox.proMode, t.inputBox.proModeDescription],
    ultra: [t.inputBox.ultraMode, t.inputBox.ultraModeDescription],
  } as Record<InputMode, [string, string]>;
}

export function ModeMenu({
  mode,
  supportsThinking,
  onSelect,
}: {
  mode: InputMode;
  supportsThinking: boolean;
  onSelect: (mode: InputMode) => void;
}) {
  const { t } = useI18n();
  const labels = useModeLabels();
  // Reasoning ("thinking") exists only where the model can think, as before.
  const modes: InputMode[] = supportsThinking
    ? ["flash", "thinking", "pro", "ultra"]
    : ["flash", "pro", "ultra"];
  return (
    <DropdownMenu>
      <ModeHoverGuide mode={mode}>
        <DropdownMenuTrigger asChild>
          <button
            type="button"
            className={PILL}
            aria-label={`Mode: ${labels[mode][0]}`}
          >
            <span className={LABEL}>Mode</span>
            {labels[mode][0]}
            <ChevronDownIcon
              className="text-muted-foreground size-3.5"
              aria-hidden
            />
          </button>
        </DropdownMenuTrigger>
      </ModeHoverGuide>
      <DropdownMenuContent align="end" className="w-80">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="text-muted-foreground text-xs">
            {t.inputBox.mode}
          </DropdownMenuLabel>
          {modes.map((m) => (
            <DropdownMenuItem key={m} onSelect={() => onSelect(m)}>
              <div className="flex flex-col gap-1">
                <span
                  className={cn("font-medium", m === mode && "text-primary")}
                >
                  {labels[m][0]}
                </span>
                <span className="text-muted-foreground text-xs">
                  {labels[m][1]}
                </span>
              </div>
              {m === mode ? (
                <CheckIcon
                  className="text-primary ml-auto size-4"
                  aria-label="Selected"
                />
              ) : (
                <span className="ml-auto size-4" />
              )}
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function EffortMenu({
  effort,
  onSelect,
}: {
  effort: ReasoningEffort | undefined;
  onSelect: (effort: ReasoningEffort) => void;
}) {
  const { t } = useI18n();
  const labels: Record<ReasoningEffort, [string, string]> = {
    minimal: [
      t.inputBox.reasoningEffortMinimal,
      t.inputBox.reasoningEffortMinimalDescription,
    ],
    low: [
      t.inputBox.reasoningEffortLow,
      t.inputBox.reasoningEffortLowDescription,
    ],
    medium: [
      t.inputBox.reasoningEffortMedium,
      t.inputBox.reasoningEffortMediumDescription,
    ],
    high: [
      t.inputBox.reasoningEffortHigh,
      t.inputBox.reasoningEffortHighDescription,
    ],
  };
  // No explicit effort reads as Medium, as it always has.
  const current = effort ?? "medium";
  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <button
          type="button"
          className={PILL}
          aria-label={`${t.inputBox.reasoningEffort}: ${labels[current][0]}`}
          data-testid="effort-trigger"
        >
          <span className={LABEL}>Effort</span>
          {labels[current][0]}
          <ChevronDownIcon
            className="text-muted-foreground size-3.5"
            aria-hidden
          />
        </button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-70">
        <DropdownMenuGroup>
          <DropdownMenuLabel className="text-muted-foreground text-xs">
            {t.inputBox.reasoningEffort}
          </DropdownMenuLabel>
          {(Object.keys(labels) as ReasoningEffort[]).map((e) => (
            <DropdownMenuItem key={e} onSelect={() => onSelect(e)}>
              <div className="flex flex-col gap-1">
                <span
                  className={cn("font-medium", e === current && "text-primary")}
                >
                  {labels[e][0]}
                </span>
                <span className="text-muted-foreground text-xs">
                  {labels[e][1]}
                </span>
              </div>
              {e === current ? (
                <CheckIcon
                  className="text-primary ml-auto size-4"
                  aria-label="Selected"
                />
              ) : (
                <span className="ml-auto size-4" />
              )}
            </DropdownMenuItem>
          ))}
        </DropdownMenuGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}

export function ModelMenu({
  models,
  selected,
  open,
  onOpenChange,
  onSelect,
}: {
  models: Model[];
  selected: Model | undefined;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (name: string) => void;
}) {
  const { t } = useI18n();
  const provider = modelProvider(selected?.model);
  return (
    <ModelSelector open={open} onOpenChange={onOpenChange}>
      <ModelSelectorTrigger asChild>
        <button
          type="button"
          className={cn(PILL, provider && "pl-2")}
          aria-label={`Model: ${selected?.display_name ?? "none available"}`}
        >
          {provider && <BrandLogo source={provider} size={20} />}
          <ModelSelectorName className="max-w-48 truncate text-sm">
            {selected?.display_name ?? "No model"}
          </ModelSelectorName>
          <ChevronDownIcon
            className="text-muted-foreground size-3.5"
            aria-hidden
          />
        </button>
      </ModelSelectorTrigger>
      <ModelSelectorContent>
        <ModelSelectorInput placeholder={t.inputBox.searchModels} />
        <ModelSelectorList>
          {models.map((m) => (
            <ModelSelectorItem
              key={m.name}
              value={m.name}
              onSelect={() => onSelect(m.name)}
            >
              <div className="flex min-w-0 flex-1 flex-col">
                <ModelSelectorName>{m.display_name}</ModelSelectorName>
                <span className="text-muted-foreground truncate font-mono text-[10px]">
                  {m.model}
                </span>
              </div>
              {m.name === selected?.name ? (
                <CheckIcon className="ml-auto size-4" aria-label="Selected" />
              ) : (
                <div className="ml-auto size-4" />
              )}
            </ModelSelectorItem>
          ))}
        </ModelSelectorList>
      </ModelSelectorContent>
    </ModelSelector>
  );
}

/**
 * The one primary button. While a reply streams it is the Stop button (the
 * form's submit handler stops instead of sending).
 */
export function SendButton({
  status,
  disabled,
}: {
  status: ChatStatus;
  disabled?: boolean;
}) {
  const streaming = status === "streaming";
  const submitted = status === "submitted";
  return (
    <PromptInputSubmit
      status={status}
      disabled={disabled}
      aria-label={streaming ? "Stop" : submitted ? "Sending" : "Send"}
      data-testid="send-button"
      data-status={status}
      className="bg-primary text-primary-foreground hover:bg-primary/90 size-10 rounded-xl max-sm:size-11"
    >
      {streaming ? (
        <SquareIcon className="size-3.5 fill-current" aria-hidden />
      ) : submitted ? (
        <Loader2Icon className="size-4 animate-spin" aria-hidden />
      ) : (
        <ArrowRightIcon className="size-4" aria-hidden />
      )}
    </PromptInputSubmit>
  );
}
