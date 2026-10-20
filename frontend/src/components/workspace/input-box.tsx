"use client";

import type { ChatStatus } from "ai";
import { PaperclipIcon, XIcon } from "lucide-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ComponentProps,
  type KeyboardEvent,
} from "react";
import { toast } from "sonner";

import {
  PromptInput,
  PromptInputFooter,
  PromptInputHeader,
  PromptInputTextarea,
  PromptInputTools,
  usePromptInputAttachments,
  usePromptInputController,
  type PromptInputMessage,
} from "@/components/ai-elements/prompt-input";
import { Suggestion, Suggestions } from "@/components/ai-elements/suggestion";
import { BrandLogo } from "@/components/brand";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useAgent } from "@/core/agents/hooks";
import { useI18n } from "@/core/i18n/hooks";
import { useModels } from "@/core/models/hooks";
import type { AgentThreadContext } from "@/core/threads";
import { cn } from "@/lib/utils";

import {
  EffortMenu,
  ModeMenu,
  ModelMenu,
  SendButton,
} from "./chat-bar/bar-controls";
import {
  matchCommands,
  type PickerTab,
  type SlashCommand,
} from "./chat-bar/commands";
import { ContextChips, type ChatAgent } from "./chat-bar/context-chips";
import {
  agentChatHref,
  ContextPicker,
  MULTI_AGENT_LATER,
} from "./chat-bar/context-picker";
import {
  effortForMode,
  findTrigger,
  getResolvedMode,
  mentionToken,
  agentSkills,
  selectedIntegrations,
  showsReasoningEffort,
  type InputMode,
  type ReasoningEffort,
  type Trigger,
} from "./chat-bar/logic";
import { SuggestMenu, type SuggestItem } from "./chat-bar/suggest-menu";
import {
  useAgentChoices,
  useChatProjects,
  useChatUploads,
  useSkillChoices,
  useThreadIntegrations,
} from "./chat-bar/use-chat-bar-data";
import { useFollowups } from "./chat-bar/use-followups";
import { WelcomeSuggestions } from "./chat-bar/welcome-suggestions";
import { useThread } from "./messages/context";
import { Tooltip } from "./tooltip";

type BarContext = Omit<
  AgentThreadContext,
  "thread_id" | "is_plan_mode" | "thinking_enabled" | "subagent_enabled"
> & {
  mode: InputMode | undefined;
  reasoning_effort?: ReasoningEffort;
};

/** The thread's own agent when the chat is not an agent chat. */
const LEAD_AGENT = "Lead agent";

/**
 * The chat bar (Feature 006, Chat.dc.html), used by every chat: context chips
 * and the "+" picker above the message, attach · mode · effort · model · send
 * below it, "@" to call in an agent and "/" for commands.
 */
export function InputBox({
  className,
  disabled,
  autoFocus,
  status = "ready",
  context,
  extraHeader,
  isWelcomeMode,
  threadId,
  initialValue,
  onContextChange,
  onFollowupsVisibilityChange,
  onSubmit,
  onStop,
  ...props
}: Omit<ComponentProps<typeof PromptInput>, "onSubmit"> & {
  assistantId?: string | null;
  status?: ChatStatus;
  disabled?: boolean;
  context: BarContext;
  extraHeader?: React.ReactNode;
  /**
   * Whether to render the input in welcome layout (vertically centered,
   * with hero + quick action suggestions).  This is purely a visual flag,
   * decoupled from "the backend has created the thread" — see issue #2746.
   */
  isWelcomeMode?: boolean;
  threadId: string;
  initialValue?: string;
  onContextChange?: (context: BarContext) => void;
  onFollowupsVisibilityChange?: (visible: boolean) => void;
  onSubmit?: (message: PromptInputMessage) => void;
  onStop?: () => void;
}) {
  const { t } = useI18n();
  const router = useRouter();
  const searchParams = useSearchParams();
  const params = useParams<{ agent_name?: string }>();
  const { models } = useModels();
  const { thread } = useThread();
  const { textInput, attachments } = usePromptInputController();
  const promptRootRef = useRef<HTMLDivElement | null>(null);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const plusRef = useRef<HTMLButtonElement | null>(null);
  const menuId = useId();

  const [modelDialogOpen, setModelDialogOpen] = useState(false);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [pickerTab, setPickerTab] = useState<PickerTab>("integrations");
  const [trigger, setTrigger] = useState<Trigger | null>(null);
  const [activeIndex, setActiveIndex] = useState(0);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [pendingSuggestion, setPendingSuggestion] = useState<string | null>(
    null,
  );

  const text = textInput.value ?? "";

  // ---- model, mode, effort (behaviour unchanged) ---------------------------

  useEffect(() => {
    if (models.length === 0) {
      return;
    }
    const currentModel = models.find((m) => m.name === context.model_name);
    const fallbackModel = currentModel ?? models[0]!;
    const supportsThinking = fallbackModel.supports_thinking ?? false;
    const nextModelName = fallbackModel.name;
    const nextMode = getResolvedMode(context.mode, supportsThinking);
    if (context.model_name === nextModelName && context.mode === nextMode) {
      return;
    }
    onContextChange?.({
      ...context,
      model_name: nextModelName,
      mode: nextMode,
    });
  }, [context, models, onContextChange]);

  const selectedModel = useMemo(() => {
    if (models.length === 0) {
      return undefined;
    }
    return models.find((m) => m.name === context.model_name) ?? models[0];
  }, [context.model_name, models]);
  const resolvedModelName = selectedModel?.name;
  const supportThinking = selectedModel?.supports_thinking ?? false;
  const supportReasoningEffort =
    selectedModel?.supports_reasoning_effort ?? false;
  const mode: InputMode = context.mode ?? "flash";

  const handleModelSelect = useCallback(
    (model_name: string) => {
      const model = models.find((m) => m.name === model_name);
      if (!model) {
        return;
      }
      onContextChange?.({
        ...context,
        model_name,
        mode: getResolvedMode(context.mode, model.supports_thinking ?? false),
        reasoning_effort: context.reasoning_effort,
      });
      setModelDialogOpen(false);
    },
    [onContextChange, context, models],
  );

  const handleModeSelect = useCallback(
    (next: InputMode) => {
      onContextChange?.({
        ...context,
        mode: getResolvedMode(next, supportThinking),
        reasoning_effort: effortForMode(next),
      });
    },
    [onContextChange, context, supportThinking],
  );

  const handleReasoningEffortSelect = useCallback(
    (effort: ReasoningEffort) => {
      onContextChange?.({ ...context, reasoning_effort: effort });
    },
    [onContextChange, context],
  );

  // ---- context: projects, agents, integrations, skills, files --------------

  const integrations = useThreadIntegrations(threadId);
  const chatProjects = useChatProjects(
    threadId,
    thread.values.title ?? undefined,
  );
  const wantAgents =
    trigger?.kind === "@" || (pickerOpen && pickerTab === "agents");
  const { agents, error: agentsError } = useAgentChoices(wantAgents);
  const { skills: enabledSkills, error: skillsError } = useSkillChoices(true);
  const threadAgentName = params?.agent_name;
  const { agent: threadAgentConfig } = useAgent(threadAgentName);
  const uploaded = useChatUploads(
    threadId,
    !isWelcomeMode && pickerOpen && pickerTab === "files",
  );

  /** Nothing sent yet: "@" may still choose the agent the chat starts with. */
  const isNewChat = !!isWelcomeMode;
  const threadAgent = threadAgentName ?? LEAD_AGENT;
  const chatAgents: ChatAgent[] = useMemo(
    () => [{ name: threadAgent, role: "thread" }],
    [threadAgent],
  );
  // Read-only (Open Question 7): what this chat's agent may use.
  const agentSkillList = useMemo(() => {
    const names = agentSkills(
      enabledSkills.map((s) => s.name),
      threadAgentName ? threadAgentConfig?.skills : null,
    );
    return enabledSkills.filter((s) => names.includes(s.name));
  }, [enabledSkills, threadAgentConfig, threadAgentName]);

  const setText = useCallback(
    (next: string, caret?: number) => {
      textInput.setInput(next);
      requestAnimationFrame(() => {
        const el = textareaRef.current;
        if (!el) return;
        el.focus();
        const at = caret ?? next.length;
        el.setSelectionRange(at, at);
      });
    },
    [textInput],
  );

  const openPicker = useCallback((tab?: PickerTab) => {
    if (tab) setPickerTab(tab);
    setPickerOpen(true);
  }, []);
  const closePicker = useCallback(() => {
    setPickerOpen(false);
    plusRef.current?.focus();
  }, []);

  const attachProject = useCallback(
    (projectId: string) => {
      const project = chatProjects.projects.find((p) => p.id === projectId);
      chatProjects.attach.mutate(projectId, {
        onSuccess: () => toast(`Attached to ${project?.name ?? "the project"}`),
        onError: (e) => toast.error(e.message),
      });
    },
    [chatProjects],
  );

  // ---- "@" and "/" ----------------------------------------------------------

  const refreshTrigger = useCallback(() => {
    const el = textareaRef.current;
    if (!el) return;
    const next = findTrigger(el.value, el.selectionStart ?? el.value.length);
    setTrigger((prev) => {
      if (prev?.kind !== next?.kind || prev?.query !== next?.query) {
        setActiveIndex(0);
      }
      return next;
    });
  }, []);

  const agentMatches = useMemo(() => {
    if (trigger?.kind !== "@") return [];
    const q = trigger.query.toLowerCase();
    return agents
      .filter(
        (a) =>
          mentionToken(a.name).slice(1).toLowerCase().startsWith(q) ||
          a.name.toLowerCase().includes(q),
      )
      .slice(0, 8);
  }, [agents, trigger]);

  const commandMatches: SlashCommand[] = useMemo(
    () => (trigger?.kind === "/" ? matchCommands(trigger.query) : []),
    [trigger],
  );

  const menuItems: SuggestItem[] =
    trigger?.kind === "@"
      ? agentMatches.map((a) => ({
          key: a.name,
          label: a.name,
          hint:
            a.name === threadAgent
              ? "In this chat"
              : isNewChat
                ? a.description || "Start the chat with this agent"
                : MULTI_AGENT_LATER,
          disabled: !isNewChat || a.name === threadAgent,
          leading: (
            <BrandLogo source={null} name={a.name} size={26} decorative />
          ),
        }))
      : commandMatches.map((c) => ({
          key: c.name,
          label: `/${c.name}`,
          hint: c.description,
        }));

  const runCommand = useCallback(
    (cmd: SlashCommand, clearedText: string) => {
      setText(clearedText, 0);
      switch (cmd.action.kind) {
        case "new-chat":
          router.push("/workspace/chats/new");
          return;
        case "open-picker":
          openPicker(cmd.action.tab);
          return;
        case "attach":
          attachments.openFileDialog();
          return;
      }
    },
    [attachments, openPicker, router, setText],
  );

  const pick = useCallback(
    (index: number) => {
      const el = textareaRef.current;
      if (!trigger || !el) return;
      const caret = el.selectionStart ?? el.value.length;
      if (trigger.kind === "@") {
        // Open Question 8: in a new chat, "@" starts the chat with that
        // agent (its own chat route); in an existing chat it is disabled.
        const agent = agentMatches[index];
        if (!agent || !isNewChat || agent.name === threadAgent) return;
        router.push(agentChatHref(agent.name));
      } else {
        const cmd = commandMatches[index];
        if (!cmd) return;
        const rest = el.value.slice(caret).replace(/^ /, "");
        runCommand(cmd, rest);
      }
      setTrigger(null);
    },
    [
      agentMatches,
      commandMatches,
      isNewChat,
      router,
      runCommand,
      threadAgent,
      trigger,
    ],
  );

  /**
   * Runs before the message box's own keys (Enter sends): while a dropdown is
   * open, the arrows, Enter, Tab and Esc belong to it.
   */
  const onKeyDownCapture = useCallback(
    (e: KeyboardEvent<HTMLTextAreaElement>) => {
      if (!trigger) return;
      const count = menuItems.length;
      const own = () => {
        e.preventDefault();
        e.stopPropagation();
      };
      if (e.key === "Escape") {
        own();
        setTrigger(null);
      } else if (e.key === "ArrowDown" && count > 0) {
        own();
        setActiveIndex((i) => (i + 1) % count);
      } else if (e.key === "ArrowUp" && count > 0) {
        own();
        setActiveIndex((i) => (i - 1 + count) % count);
      } else if (
        (e.key === "Enter" || e.key === "Tab") &&
        count > 0 &&
        !e.shiftKey
      ) {
        own();
        pick(Math.min(activeIndex, count - 1));
      }
    },
    [activeIndex, menuItems.length, pick, trigger],
  );

  // ---- send / stop ----------------------------------------------------------

  const {
    followups,
    hidden: followupsHidden,
    setHidden: setFollowupsHidden,
    loading: followupsLoading,
    reset: resetFollowups,
  } = useFollowups({
    status,
    disabled,
    threadId,
    modelName: context.model_name as string | undefined,
  });

  const handleSubmit = useCallback(
    async (message: PromptInputMessage) => {
      if (status === "streaming") {
        onStop?.();
        return;
      }
      if (!message.text) {
        return;
      }
      resetFollowups();
      setTrigger(null);
      setPickerOpen(false);
      const outgoing = message;

      // Guard against submitting before the initial model auto-selection
      // effect has flushed thread settings to storage/state.
      if (resolvedModelName && context.model_name !== resolvedModelName) {
        onContextChange?.({
          ...context,
          model_name: resolvedModelName,
          mode: getResolvedMode(
            context.mode,
            selectedModel?.supports_thinking ?? false,
          ),
        });
        setTimeout(() => onSubmit?.(outgoing), 0);
        return;
      }
      onSubmit?.(outgoing);
    },
    [
      context,
      onContextChange,
      onSubmit,
      onStop,
      resetFollowups,
      resolvedModelName,
      selectedModel?.supports_thinking,
      status,
    ],
  );

  const requestFormSubmit = useCallback(() => {
    const form = promptRootRef.current?.querySelector("form");
    form?.requestSubmit();
  }, []);

  const handleFollowupClick = useCallback(
    (suggestion: string) => {
      if (status === "streaming") {
        return;
      }
      if (text.trim()) {
        setPendingSuggestion(suggestion);
        setConfirmOpen(true);
        return;
      }
      textInput.setInput(suggestion);
      setFollowupsHidden(true);
      setTimeout(() => requestFormSubmit(), 0);
    },
    [requestFormSubmit, setFollowupsHidden, status, text, textInput],
  );

  const confirmSend = useCallback(
    (how: "replace" | "append") => {
      if (!pendingSuggestion) {
        setConfirmOpen(false);
        return;
      }
      const current = text.trim();
      textInput.setInput(
        how === "append" && current
          ? `${current}\n${pendingSuggestion}`
          : pendingSuggestion,
      );
      setFollowupsHidden(true);
      setConfirmOpen(false);
      setPendingSuggestion(null);
      setTimeout(() => requestFormSubmit(), 0);
    },
    [pendingSuggestion, requestFormSubmit, setFollowupsHidden, text, textInput],
  );

  const showFollowups =
    !disabled &&
    !isWelcomeMode &&
    !followupsHidden &&
    (followupsLoading || followups.length > 0);

  const followupsVisibilityChangeRef = useRef(onFollowupsVisibilityChange);
  useEffect(() => {
    followupsVisibilityChangeRef.current = onFollowupsVisibilityChange;
  }, [onFollowupsVisibilityChange]);
  useEffect(() => {
    followupsVisibilityChangeRef.current?.(showFollowups);
  }, [showFollowups]);
  useEffect(() => {
    return () => followupsVisibilityChangeRef.current?.(false);
  }, []);

  const menuOpen = !!trigger;
  const chipIntegrations = selectedIntegrations(integrations.rows);

  return (
    <div ref={promptRootRef} className="relative flex flex-col gap-4">
      {showFollowups && (
        <div className="flex items-center justify-center pb-2">
          <div className="flex items-center gap-2">
            {followupsLoading ? (
              <div className="text-muted-foreground bg-background/80 rounded-full border px-4 py-2 text-xs backdrop-blur-sm">
                {t.inputBox.followupLoading}
              </div>
            ) : (
              <Suggestions className="min-h-16 w-fit items-start">
                {followups.map((s) => (
                  <Suggestion
                    key={s}
                    suggestion={s}
                    onClick={() => handleFollowupClick(s)}
                  />
                ))}
                <Button
                  aria-label={t.common.close}
                  className="text-muted-foreground cursor-pointer rounded-full px-3 text-xs font-normal"
                  variant="outline"
                  size="sm"
                  type="button"
                  onClick={() => setFollowupsHidden(true)}
                >
                  <XIcon className="size-4" />
                </Button>
              </Suggestions>
            )}
          </div>
        </div>
      )}
      <div className="relative" data-testid="chat-bar">
        {menuOpen && (
          <SuggestMenu
            id={menuId}
            title={trigger.kind === "@" ? "Call in an agent" : "Commands"}
            items={menuItems}
            active={Math.min(activeIndex, Math.max(0, menuItems.length - 1))}
            empty={
              trigger.kind === "@"
                ? agentsError
                  ? "Agents could not be loaded."
                  : "No agent matches."
                : "No command matches."
            }
            onPick={pick}
            onHover={setActiveIndex}
          />
        )}
        {pickerOpen && (
          <ContextPicker
            placement={isWelcomeMode ? "bottom" : "top"}
            isNewChat={isNewChat}
            tab={pickerTab}
            onTabChange={setPickerTab}
            onClose={closePicker}
            projects={chatProjects.projects}
            attachedProjects={chatProjects.attached}
            onAttachProject={attachProject}
            agents={agents}
            agentsError={agentsError}
            threadAgent={threadAgent}
            integrations={integrations.rows}
            integrationsLoading={integrations.loading}
            integrationsError={integrations.error}
            statusError={integrations.statusError}
            overCap={integrations.overCap}
            count={integrations.count}
            onToggleIntegration={integrations.setSelected}
            connectorsAvailable={integrations.connectorsAvailable}
            skills={agentSkillList}
            skillsError={skillsError}
            files={attachments.files}
            uploaded={uploaded}
            onAttachFiles={() => attachments.openFileDialog()}
            onRemoveFile={attachments.remove}
          />
        )}
        <PromptInput
          className={cn(
            "*:data-[slot='input-group']:bg-card *:data-[slot='input-group']:border-border-strong rounded-2xl transition-all duration-300 ease-out *:data-[slot='input-group']:rounded-2xl",
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
          <PromptInputHeader className="px-3.5 pt-3">
            <ContextChips
              ref={plusRef}
              projects={chatProjects.attached.map((a) => ({
                link_id: a.link_id,
                name: a.project.name,
              }))}
              onDetachProject={(linkId) =>
                chatProjects.detach.mutate(linkId, {
                  onError: (e) => toast.error(e.message),
                })
              }
              agents={chatAgents}
              integrations={chipIntegrations}
              onRemoveIntegration={(id) => integrations.setSelected(id, false)}
              skills={agentSkillList.map((s) => s.name)}
              files={attachments.files}
              onRemoveFile={attachments.remove}
              pickerOpen={pickerOpen}
              onOpenPicker={() => (pickerOpen ? closePicker() : openPicker())}
              disabled={disabled}
            />
          </PromptInputHeader>
          <PromptInputTextarea
            ref={textareaRef}
            className="min-h-12 px-3.5 text-[15px]"
            disabled={disabled}
            placeholder={
              isWelcomeMode
                ? t.inputBox.placeholder
                : "Ask anything · @ to bring in an agent · / for commands"
            }
            aria-label="Message"
            autoFocus={autoFocus}
            defaultValue={initialValue}
            role={menuOpen ? "combobox" : undefined}
            aria-expanded={menuOpen ? true : undefined}
            aria-controls={menuOpen ? menuId : undefined}
            aria-autocomplete={menuOpen ? "list" : undefined}
            aria-activedescendant={
              menuOpen && menuItems.length > 0
                ? `${menuId}-opt-${Math.min(activeIndex, menuItems.length - 1)}`
                : undefined
            }
            onKeyDownCapture={onKeyDownCapture}
            onChange={() => requestAnimationFrame(refreshTrigger)}
            onSelect={refreshTrigger}
            onBlur={() => setTrigger(null)}
          />
          <PromptInputFooter className="flex flex-wrap gap-2 px-3.5 pb-3">
            <PromptInputTools>
              <AttachButton disabled={disabled} />
            </PromptInputTools>
            <PromptInputTools className="flex-wrap justify-end gap-2">
              <ModeMenu
                mode={mode}
                supportsThinking={supportThinking}
                onSelect={handleModeSelect}
              />
              {showsReasoningEffort(supportReasoningEffort, context.mode) && (
                <EffortMenu
                  effort={context.reasoning_effort}
                  onSelect={handleReasoningEffortSelect}
                />
              )}
              <ModelMenu
                models={models}
                selected={selectedModel}
                open={modelDialogOpen}
                onOpenChange={setModelDialogOpen}
                onSelect={handleModelSelect}
              />
              <SendButton status={status} disabled={disabled} />
            </PromptInputTools>
          </PromptInputFooter>
          {!isWelcomeMode && (
            <div className="bg-background absolute right-0 -bottom-[17px] left-0 z-0 h-4"></div>
          )}
        </PromptInput>
      </div>

      {isWelcomeMode && searchParams.get("mode") !== "skill" && (
        <div className="flex items-center justify-center pt-2">
          <WelcomeSuggestions />
        </div>
      )}

      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{t.inputBox.followupConfirmTitle}</DialogTitle>
            <DialogDescription>
              {t.inputBox.followupConfirmDescription}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmOpen(false)}>
              {t.common.cancel}
            </Button>
            <Button variant="secondary" onClick={() => confirmSend("append")}>
              {t.inputBox.followupConfirmAppend}
            </Button>
            <Button onClick={() => confirmSend("replace")}>
              {t.inputBox.followupConfirmReplace}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function AttachButton({ disabled }: { disabled?: boolean }) {
  const { t } = useI18n();
  const attachments = usePromptInputAttachments();
  return (
    <Tooltip content={t.inputBox.addAttachments}>
      <button
        type="button"
        aria-label="Attach file"
        disabled={disabled}
        onClick={() => attachments.openFileDialog()}
        className="text-muted-foreground hover:text-foreground focus-visible:ring-ring inline-flex size-9 items-center justify-center rounded-md focus-visible:ring-2 focus-visible:outline-none disabled:opacity-50 max-sm:size-11"
      >
        <PaperclipIcon className="size-[18px]" aria-hidden />
      </button>
    </Tooltip>
  );
}
