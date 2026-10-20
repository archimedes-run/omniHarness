"use client";

import type { ChatStatus } from "ai";
import { PaperclipIcon, XIcon } from "lucide-react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
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
import { usePreferences } from "@/core/preferences/hooks";
import type { AgentThreadContext } from "@/core/threads";
import { cn } from "@/lib/utils";

import { AgentAvatar } from "./chat-bar/agent-avatar";
import {
  EffortMenu,
  ModeMenu,
  ModelMenu,
  SendButton,
} from "./chat-bar/bar-controls";
import { backspaceToChips, insertMention } from "./chat-bar/chips";
import {
  matchCommands,
  type PickerTab,
  type SlashCommand,
} from "./chat-bar/commands";
import {
  ContextChips,
  type ChatAgent,
  type ChipsHandle,
} from "./chat-bar/context-chips";
import { ContextPicker, MULTI_AGENT_LATER } from "./chat-bar/context-picker";
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
  useThreadSkills,
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
  chosenAgent,
  onChooseAgent,
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
  /**
   * The agent picked with "@" (or the picker) before the first message; the
   * page starts the chat with it. Only the plain new-chat page offers this.
   */
  chosenAgent?: string | null;
  onChooseAgent?: (name: string | null) => void;
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
  const chipsRef = useRef<ChipsHandle | null>(null);
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
  const routeAgent = params?.agent_name;
  // The chat's agent: its route's, else one picked before the first message.
  const threadAgentName = routeAgent ?? chosenAgent ?? undefined;
  const { agent: threadAgentConfig } = useAgent(threadAgentName);
  const threadSkills = useThreadSkills(threadId);
  const uploaded = useChatUploads(
    threadId,
    !isWelcomeMode && pickerOpen && pickerTab === "files",
  );

  /** Nothing sent yet: "@" may still choose the agent the chat starts with. */
  const isNewChat = !!isWelcomeMode;
  const threadAgent = threadAgentName ?? LEAD_AGENT;
  const canChooseAgent = isNewChat && !routeAgent && !!onChooseAgent;
  const chatAgents: ChatAgent[] = useMemo(
    () => [
      {
        name: threadAgent,
        role: !routeAgent && chosenAgent ? "chosen" : "thread",
      },
    ],
    [chosenAgent, routeAgent, threadAgent],
  );
  // Read-only (Open Question 7): what this chat's agent may use.
  const agentSkillList = useMemo(() => {
    const names = agentSkills(
      enabledSkills.map((s) => s.name),
      threadAgentName ? threadAgentConfig?.skills : null,
    );
    return enabledSkills.filter((s) => names.includes(s.name));
  }, [enabledSkills, threadAgentConfig, threadAgentName]);

  // The caret goes where setText says as soon as the new text is committed,
  // before the next key is handled: a frame later, a fast typist's next
  // letter would already have landed at the end.
  const pendingCaret = useRef<number | null>(null);
  useLayoutEffect(() => {
    const el = textareaRef.current;
    const at = pendingCaret.current;
    if (!el || at === null || el.value !== text) return;
    pendingCaret.current = null;
    el.focus();
    el.setSelectionRange(at, at);
  }, [text]);
  const setText = useCallback(
    (next: string, caret?: number) => {
      pendingCaret.current = caret ?? next.length;
      textInput.setInput(next);
      if (next === textareaRef.current?.value) {
        // Unchanged text commits nothing: place the caret now.
        const at = pendingCaret.current;
        pendingCaret.current = null;
        textareaRef.current.focus();
        textareaRef.current.setSelectionRange(at, at);
      }
    },
    [textInput],
  );

  const openPicker = useCallback((tab?: PickerTab) => {
    if (tab) setPickerTab(tab);
    setPickerOpen(true);
  }, []);
  const closePicker = useCallback(() => {
    setPickerOpen(false);
    chipsRef.current?.focusAdd();
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
              : canChooseAgent
                ? a.description || "Start the chat with this agent"
                : MULTI_AGENT_LATER,
          disabled: !canChooseAgent || a.name === threadAgent,
          leading: <AgentAvatar id={a.name} name={a.name} />,
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
        // Open Question 8: in a new chat, "@" picks the agent the chat
        // starts with: a chip, the typed text kept on both sides of the
        // mention and the caret right after it. In an existing chat it is
        // disabled (multi-agent chat comes later).
        const agent = agentMatches[index];
        if (!agent || !canChooseAgent || agent.name === threadAgent) return;
        const next = insertMention(el.value, trigger, caret, agent.name);
        setText(next.text, next.caret);
        onChooseAgent?.(agent.name);
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
      canChooseAgent,
      commandMatches,
      onChooseAgent,
      runCommand,
      setText,
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
      // Backspace in an empty message goes to the chips (a second one, on
      // the chip, removes it). It also keeps the old "remove the last
      // attachment" shortcut from firing underneath.
      if (
        e.key === "Backspace" &&
        !trigger &&
        backspaceToChips(e.currentTarget.value, 1) &&
        chipsRef.current?.focusLast()
      ) {
        e.preventDefault();
        e.stopPropagation();
        return;
      }
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
  const { displayName } = usePreferences();
  // No name until it can be told: never a guessed one.
  const heading = displayName
    ? `What are we working on, ${displayName}?`
    : "What are we working on?";

  return (
    <div ref={promptRootRef} className="relative flex flex-col gap-5">
      {/* The bar stays at the bottom of every chat, new ones included; the
          heading sits up in the empty page and the starters above the bar. */}
      {isWelcomeMode && !extraHeader && (
        <div className="flex min-h-[32vh] items-start justify-center">
          <h1 className="text-center text-[30px] leading-tight font-semibold tracking-[-0.01em]">
            {heading}
          </h1>
        </div>
      )}
      {isWelcomeMode && searchParams.get("mode") !== "skill" && (
        <WelcomeSuggestions />
      )}
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
            canChooseAgent={canChooseAgent}
            onChooseAgent={(name) => {
              onChooseAgent?.(name);
              closePicker();
            }}
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
            excludedSkills={threadSkills.excluded}
            chatSkillsError={threadSkills.error}
            onToggleSkill={threadSkills.setUsed}
            files={attachments.files}
            uploaded={uploaded}
            onAttachFiles={() => attachments.openFileDialog()}
            onRemoveFile={attachments.remove}
          />
        )}
        <PromptInput
          className={cn(
            "*:data-[slot='input-group']:bg-card *:data-[slot='input-group']:border-border-strong rounded-[20px] transition-all duration-300 ease-out *:data-[slot='input-group']:gap-3 *:data-[slot='input-group']:rounded-[20px] *:data-[slot='input-group']:px-4 *:data-[slot='input-group']:pt-3.5 *:data-[slot='input-group']:pb-3 *:data-[slot='input-group']:shadow-lg",
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
          <PromptInputHeader className="p-0">
            <ContextChips
              ref={chipsRef}
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
              onRemoveAgent={() => onChooseAgent?.(null)}
              integrations={chipIntegrations}
              onRemoveIntegration={(id) => integrations.setSelected(id, false)}
              files={attachments.files}
              onRemoveFile={attachments.remove}
              pickerOpen={pickerOpen}
              onOpenPicker={() => (pickerOpen ? closePicker() : openPicker())}
              onExit={() => textareaRef.current?.focus()}
              disabled={disabled}
            />
          </PromptInputHeader>
          <PromptInputTextarea
            ref={textareaRef}
            // 16 px, two rows to start, growing to ten (24 px a row).
            className="max-h-[248px] min-h-14 overflow-y-auto px-0.5 py-1 text-base leading-6 md:text-base"
            disabled={disabled}
            placeholder="Ask anything · @ to bring in an agent · / for commands"
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
          <PromptInputFooter className="flex flex-wrap gap-2 p-0">
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
        className="text-foreground-2 hover:text-foreground hover:bg-surface-raised focus-visible:ring-ring inline-flex size-[38px] items-center justify-center rounded-[10px] focus-visible:ring-2 focus-visible:outline-none disabled:opacity-50 max-sm:size-11"
      >
        <PaperclipIcon className="size-5" aria-hidden />
      </button>
    </Tooltip>
  );
}
