"use client";

import {
  FolderIcon,
  LockIcon,
  PaperclipIcon,
  PlusIcon,
  XIcon,
} from "lucide-react";
import {
  Fragment,
  forwardRef,
  useEffect,
  useImperativeHandle,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { BrandLogo } from "@/components/brand";
import { cn } from "@/lib/utils";

import { AgentAvatar } from "./agent-avatar";
import {
  INTEGRATIONS_SHOWN,
  chipKey,
  collapse,
  isUnhealthy,
  isUnknown,
} from "./chips";
import type { IntegrationRow } from "./logic";

/**
 * One agent in the chat. Phase 1 has one: the thread's own, or the one picked
 * with "@" before the first message (that one can be removed again).
 */
export interface ChatAgent {
  name: string;
  role: "thread" | "chosen";
}

export interface ChipsHandle {
  /** Backspace in an empty message: the last chip takes focus. */
  focusLast: () => boolean;
  focusAdd: () => void;
}

// Chat-Bar-v2.dc.html: 34 px tall, 17 px radius, 14 px text, 1 px border.
const CHIP =
  "bg-surface-raised text-foreground border-border-strong inline-flex h-[34px] max-w-full items-center gap-2 rounded-[17px] border text-sm outline-none focus-visible:ring-2 focus-visible:ring-ring";
const PILL_BUTTON =
  "border-border-strong text-foreground-2 hover:text-foreground hover:bg-surface-raised focus-visible:ring-ring inline-flex h-[34px] items-center rounded-[17px] border px-3 text-sm outline-none focus-visible:ring-2 disabled:opacity-50";

const plural = (n: number, word: string) => (n === 1 ? word : `${word}s`);

interface Item {
  key: string;
  testId: string;
  label: string;
  leading: ReactNode;
  /** Words after the name: an integration's state when it is not working. */
  note?: ReactNode;
  tone?: "warn";
  removeLabel?: string;
  onRemove?: () => void;
  /** Shown instead of × on a chip that cannot be removed. */
  locked?: string;
  padLeft: string;
}

function RemoveButton({
  label,
  onClick,
}: {
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      onClick={onClick}
      className="text-muted-foreground hover:bg-border-strong hover:text-foreground focus-visible:ring-ring inline-flex size-[26px] shrink-0 items-center justify-center rounded-full outline-none focus-visible:ring-2"
    >
      <XIcon className="size-4" aria-hidden />
    </button>
  );
}

/**
 * The context row above the message (Chat-Bar-v2.dc.html): every piece of
 * context is its own chip, removable right here. Project, agent,
 * integrations and files, then "Add", which opens the picker. Skills are
 * not chips (they are set in the picker's Skills tab).
 *
 * A chip that cannot be removed says why instead of offering ×: a pinned
 * integration is always on; the chat's own agent stays (Phase 1 has one
 * agent per chat). An integration that is not working stays visible with a
 * dashed warn border and its state in words; overflow never hides it.
 *
 * Keyboard: arrows move between chips, Delete or Backspace removes the
 * focused one, Esc goes back to the message.
 */
export const ContextChips = forwardRef<
  ChipsHandle,
  {
    projects: { link_id: string; name: string }[];
    onDetachProject: (linkId: string) => void;
    agents: ChatAgent[];
    onRemoveAgent: (name: string) => void;
    integrations: IntegrationRow[];
    onRemoveIntegration: (id: string) => void;
    files: {
      id: string;
      filename?: string;
      mediaType?: string;
      url?: string;
    }[];
    onRemoveFile: (id: string) => void;
    pickerOpen: boolean;
    onOpenPicker: () => void;
    /** Focus goes back to the message box. */
    onExit: () => void;
    disabled?: boolean;
  }
>(function ContextChips(p, ref) {
  const listRef = useRef<HTMLUListElement | null>(null);
  const addRef = useRef<HTMLButtonElement | null>(null);
  const [integrationsOpen, setIntegrationsOpen] = useState(false);
  const pendingFocus = useRef<number | null>(null);

  const ints = collapse(
    p.integrations,
    INTEGRATIONS_SHOWN,
    integrationsOpen,
    (row) => isUnhealthy(row.status),
  );

  const items: Item[] = [
    ...p.projects.map<Item>((proj) => ({
      key: `project:${proj.link_id}`,
      testId: "chip-project",
      label: proj.name,
      leading: <FolderIcon className="text-warning size-[18px]" aria-hidden />,
      removeLabel: `Remove project ${proj.name}`,
      onRemove: () => p.onDetachProject(proj.link_id),
      padLeft: "pl-2.5",
    })),
    ...p.agents.map<Item>((a) => ({
      key: `agent:${a.name}`,
      testId: "chip-agent",
      label: a.name,
      leading: <AgentAvatar id={a.name} name={a.name} size={24} />,
      ...(a.role === "chosen"
        ? {
            removeLabel: `Remove ${a.name}`,
            onRemove: () => p.onRemoveAgent(a.name),
          }
        : { locked: "A chat keeps the agent it started with" }),
      padLeft: "pl-[5px]",
    })),
    ...ints.visible.map<Item>((row) => {
      const warn = isUnhealthy(row.status);
      const unknown = isUnknown(row.status);
      return {
        key: `integration:${row.id}`,
        testId: "chip-integration",
        label: row.name,
        leading: (
          <BrandLogo
            source={row.logoSource}
            name={row.name}
            size={22}
            decorative
          />
        ),
        note:
          warn || unknown ? (
            <span
              className={cn(
                "text-xs",
                warn ? "text-warning" : "text-muted-foreground",
              )}
            >
              {row.status}
            </span>
          ) : undefined,
        tone: warn ? "warn" : undefined,
        ...(row.pinned
          ? { locked: "Always on in every chat" }
          : {
              removeLabel: `Remove ${row.name} from this chat`,
              onRemove: () => p.onRemoveIntegration(row.id),
            }),
        padLeft: "pl-1.5",
      };
    }),
    ...p.files.map<Item>((f) => {
      const isImage = !!f.url && !!f.mediaType?.startsWith("image/");
      const name = f.filename?.trim()
        ? f.filename
        : isImage
          ? "Image"
          : "Attachment";
      return {
        key: `file:${f.id}`,
        testId: "chip-file",
        label: name,
        leading: isImage ? (
          <img src={f.url} alt="" className="size-5 rounded-sm object-cover" />
        ) : (
          <PaperclipIcon className="text-muted-foreground size-4" aria-hidden />
        ),
        removeLabel: `Remove file ${f.filename?.trim() ? f.filename : "attachment"}`,
        onRemove: () => p.onRemoveFile(f.id),
        padLeft: "pl-2.5",
      };
    }),
  ];

  const chipAt = (i: number) =>
    listRef.current?.querySelector<HTMLElement>(`[data-chip-index="${i}"]`);

  useImperativeHandle(ref, () => ({
    focusLast: () => {
      const el = chipAt(items.length - 1);
      el?.focus();
      return !!el;
    },
    focusAdd: () => addRef.current?.focus(),
  }));

  // After a removal the list re-renders (now or once the server agrees);
  // focus then goes to the neighbour chosen when the key was pressed.
  const signature = items.map((i) => i.key).join("|");
  useEffect(() => {
    const target = pendingFocus.current;
    if (target === null) return;
    pendingFocus.current = null;
    const el = chipAt(Math.min(target, items.length - 1));
    if (el) el.focus();
    else p.onExit();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [signature]);

  const onKeyDown = (e: KeyboardEvent<HTMLElement>, index: number) => {
    const result = chipKey(
      e.key,
      index,
      items.map((i) => ({ removable: !!i.onRemove })),
    );
    if (!result) return;
    e.preventDefault();
    e.stopPropagation();
    if (result.kind === "focus") chipAt(result.index)?.focus();
    else if (result.kind === "textarea") p.onExit();
    else {
      if (result.focusAfter === "textarea") p.onExit();
      else pendingFocus.current = result.focusAfter;
      items[result.index]?.onRemove?.();
    }
  };

  const lastOf = (testId: string) =>
    items.map((i) => i.testId).lastIndexOf(testId);
  const moreIntegrations =
    ints.hidden > 0 ||
    (integrationsOpen && p.integrations.length > INTEGRATIONS_SHOWN);

  return (
    <ul
      ref={listRef}
      aria-label="Context for this chat"
      className="flex w-full flex-wrap items-center gap-2"
      data-testid="context-chips"
    >
      {items.map((item, index) => (
        <Fragment key={item.key}>
          <li
            data-testid={item.testId}
            data-chip-index={index}
            tabIndex={-1}
            onKeyDown={(e) => onKeyDown(e, index)}
            className={cn(
              CHIP,
              item.padLeft,
              item.onRemove ? "pr-1" : "pr-3",
              item.tone === "warn" && "border-warning border-dashed",
            )}
            title={item.locked}
          >
            {item.leading}
            <span className="max-w-48 truncate">{item.label}</span>
            {item.note}
            {item.onRemove && item.removeLabel ? (
              <RemoveButton label={item.removeLabel} onClick={item.onRemove} />
            ) : item.locked ? (
              <>
                <LockIcon
                  className="text-muted-foreground size-3.5 shrink-0"
                  aria-hidden
                />
                <span className="sr-only">. {item.locked}</span>
              </>
            ) : null}
          </li>
          {moreIntegrations && index === lastOf("chip-integration") && (
            <li>
              <button
                type="button"
                className={PILL_BUTTON}
                aria-expanded={integrationsOpen}
                aria-label={
                  integrationsOpen
                    ? "Show fewer integrations"
                    : `Show ${ints.hidden} more ${plural(ints.hidden, "integration")}`
                }
                data-testid="more-integrations"
                onClick={() => setIntegrationsOpen((o) => !o)}
              >
                {integrationsOpen
                  ? "Fewer"
                  : `+${ints.hidden} ${plural(ints.hidden, "integration")}`}
              </button>
            </li>
          )}
        </Fragment>
      ))}
      <li>
        <button
          ref={addRef}
          type="button"
          aria-label="Add context"
          aria-haspopup="dialog"
          aria-expanded={p.pickerOpen}
          data-chat-picker-trigger
          disabled={p.disabled}
          onClick={p.onOpenPicker}
          className={cn(
            "text-foreground focus-visible:ring-ring inline-flex h-[34px] items-center gap-1.5 rounded-[17px] border border-dashed pr-3.5 pl-2.5 text-sm outline-none focus-visible:ring-2 disabled:opacity-50",
            p.pickerOpen
              ? "bg-primary-subtle border-primary border-solid"
              : "border-border-strong hover:bg-surface-raised",
          )}
        >
          <PlusIcon className="size-4" aria-hidden />
          Add
        </button>
      </li>
    </ul>
  );
});
