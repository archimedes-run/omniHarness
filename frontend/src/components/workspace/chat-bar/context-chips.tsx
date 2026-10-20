"use client";

import {
  FolderIcon,
  PaperclipIcon,
  PlusIcon,
  SparklesIcon,
  XIcon,
} from "lucide-react";
import { forwardRef } from "react";

import { BrandLogo } from "@/components/brand";
import { cn } from "@/lib/utils";

import type { IntegrationRow } from "./logic";

/**
 * One agent in the chat. Phase 1 has one, the thread's own, which is not
 * removable; Phase 2 (multi-agent chat) adds "called-in" agents to the list.
 */
export interface ChatAgent {
  name: string;
  role: "thread" | "called-in";
}

const CHIP =
  "bg-surface-raised text-foreground flex min-h-8 items-center gap-1.5 rounded-md px-2 py-1 text-[13px]";

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
      className="text-muted-foreground hover:text-foreground focus-visible:ring-ring -mr-0.5 inline-flex size-6 items-center justify-center rounded focus-visible:ring-2 focus-visible:outline-none"
    >
      <XIcon className="size-3.5" aria-hidden />
    </button>
  );
}

/**
 * The row above the message (Chat.dc.html): project, agents, integrations,
 * skills and files, then "+" to add context. Project, integration and file
 * chips are removable; the agent and skills chips are read-only in Phase 1.
 */
export const ContextChips = forwardRef<
  HTMLButtonElement,
  {
    projects: { link_id: string; name: string }[];
    onDetachProject: (linkId: string) => void;
    agents: ChatAgent[];
    integrations: IntegrationRow[];
    onRemoveIntegration: (id: string) => void;
    /** Read-only (Open Question 7): the skills this chat's agent may use. */
    skills: string[];
    files: {
      id: string;
      filename?: string;
      mediaType?: string;
      url?: string;
    }[];
    onRemoveFile: (id: string) => void;
    pickerOpen: boolean;
    onOpenPicker: () => void;
    disabled?: boolean;
  }
>(function ContextChips(p, plusRef) {
  return (
    <div
      className="flex w-full flex-wrap items-center gap-2"
      data-testid="context-chips"
    >
      {p.projects.map((proj) => (
        <span key={proj.link_id} className={CHIP} data-testid="chip-project">
          <FolderIcon className="text-muted-foreground size-3.5" aria-hidden />
          <span className="max-w-40 truncate">{proj.name}</span>
          <RemoveButton
            label={`Remove project ${proj.name}`}
            onClick={() => p.onDetachProject(proj.link_id)}
          />
        </span>
      ))}

      {p.agents.length > 0 && (
        <span
          className={CHIP}
          data-testid="chip-agents"
          aria-label={`Agents in this chat: ${p.agents.map((a) => a.name).join(", ")}`}
        >
          {p.agents.map((a, i) => (
            <span key={a.name} className="flex items-center gap-1">
              {i > 0 && (
                <span aria-hidden className="text-muted-foreground">
                  ·
                </span>
              )}
              <span aria-hidden>{a.name}</span>
            </span>
          ))}
        </span>
      )}

      {p.integrations.length > 0 && (
        <span className={cn(CHIP, "gap-1")} data-testid="chip-integrations">
          <span className="sr-only">Integrations in this chat:</span>
          {p.integrations.map((row) => (
            <span key={row.id} className="group/int relative flex items-center">
              <BrandLogo source={row.logoSource} name={row.name} size={20} />
              {!row.pinned && (
                <button
                  type="button"
                  aria-label={`Turn off ${row.name} for this chat`}
                  onClick={() => p.onRemoveIntegration(row.id)}
                  className="bg-popover text-foreground border-border absolute -top-1.5 -right-1.5 flex size-4 items-center justify-center rounded-full border opacity-0 group-hover/int:opacity-100 focus-visible:opacity-100"
                >
                  <XIcon className="size-2.5" aria-hidden />
                </button>
              )}
            </span>
          ))}
        </span>
      )}

      {p.skills.length > 0 && (
        <span
          className={CHIP}
          data-testid="chip-skills"
          title={p.skills.join(", ")}
          aria-label={`Skills this chat's agent may use: ${p.skills.join(", ")}`}
        >
          <SparklesIcon
            className="text-muted-foreground size-3.5"
            aria-hidden
          />
          <span aria-hidden>
            {p.skills.length === 1 ? p.skills[0] : `${p.skills.length} skills`}
          </span>
        </span>
      )}

      {p.files.map((f) => {
        const isImage = !!f.url && !!f.mediaType?.startsWith("image/");
        return (
          <span
            key={f.id}
            className={CHIP}
            data-testid="chip-file"
            title={f.filename}
          >
            {isImage ? (
              <img
                src={f.url}
                alt=""
                className="size-4 rounded-sm object-cover"
              />
            ) : (
              <PaperclipIcon
                className="text-muted-foreground size-3.5"
                aria-hidden
              />
            )}
            <span className="max-w-40 truncate">
              {f.filename?.trim()
                ? f.filename
                : isImage
                  ? "Image"
                  : "Attachment"}
            </span>
            <RemoveButton
              label={`Remove file ${f.filename?.trim() ? f.filename : "attachment"}`}
              onClick={() => p.onRemoveFile(f.id)}
            />
          </span>
        );
      })}

      <button
        ref={plusRef}
        type="button"
        aria-label="Add context"
        aria-haspopup="dialog"
        aria-expanded={p.pickerOpen}
        data-chat-picker-trigger
        disabled={p.disabled}
        onClick={p.onOpenPicker}
        className={cn(
          "text-foreground-2 focus-visible:ring-ring inline-flex min-h-8 min-w-8 items-center justify-center rounded-md border border-dashed px-2 focus-visible:ring-2 focus-visible:outline-none disabled:opacity-50",
          p.pickerOpen
            ? "bg-primary-subtle text-foreground border-primary border-solid"
            : "border-border-strong",
        )}
      >
        <PlusIcon className="size-4" aria-hidden />
      </button>
    </div>
  );
});
