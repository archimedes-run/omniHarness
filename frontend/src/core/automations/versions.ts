import type { RuleVersion, RuleVersions } from "./api";

/**
 * The words and actions of one automation's version history (Spec 010
 * Slice 1). Pure, so the rows are unit-tested apart from rendering.
 *
 * Every action restores a version AS A NEW VERSION (the history only grows):
 * "Undo" on the latest change restores the one before it (or, for a create,
 * deletes the rule: version 0), "Restore this version" on an older one.
 */

export type VersionAction = { kind: "undo" | "restore"; toVersion: number };

export interface VersionRow {
  key: string;
  /** "v3", or "" for a hand edit not yet recorded. */
  label: string;
  at: string;
  source: string;
  changed: string;
  current: boolean;
  deleted: boolean;
  action: VersionAction | null;
}

const PLACE: Record<string, string> = {
  page: "on the Automations page",
  studio: "in Studio",
  chat: "in chat",
};

/** Who or what made the version, in words. */
export function sourceLabel(v: Pick<RuleVersion, "source" | "via">): string {
  if (v.source === "existing") {
    return v.via === "hand-edit"
      ? "Hand edit of the rules file"
      : "As it was when history began";
  }
  if (v.via === "agent-deleted") return "Switched off: its agent was deleted";
  if (v.source === "undo") return `Undone ${PLACE[v.via] ?? ""}`.trim();
  if (v.source === "chat" || v.via === "chat") return "Built in chat";
  if (v.via === "studio") return "Edited in Studio";
  if (v.via === "page") return "Edited on the Automations page";
  return "Edited";
}

const FIELD: Record<string, string> = {
  prompt: "what it asks",
  "match.schedule": "schedule",
  "match.timezone": "time zone",
  "match.event": "event",
  enabled: "on/off",
  destination: "delivery",
  name: "name",
  show_on_home: "Home",
  agent: "agent",
  urgent: "urgent",
  type: "trigger",
};

/** What changed, in one line. */
export function changedLine(
  v: Pick<RuleVersion, "changed" | "deleted" | "source">,
): string {
  if (v.deleted) return "Deleted";
  if (v.changed.includes("created")) return "Created";
  if (v.changed.length === 0) {
    return v.source === "existing" ? "The rule as it already was" : "No change";
  }
  const names = [...new Set(v.changed.map((c) => FIELD[c] ?? c))];
  const shown = names.slice(0, 3).join(", ");
  const more = names.length > 3 ? ` +${names.length - 3} more` : "";
  return `Changed ${shown}${more}`;
}

export function atText(iso: string, timeZone?: string): string {
  const d = new Date(iso);
  if (!iso || Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone,
  }).format(d);
}

/** The rows, newest first, each with the action it offers. */
export function versionRows(
  data: RuleVersions,
  timeZone?: string,
): VersionRow[] {
  const rows: VersionRow[] = [];
  const recorded = data.versions;
  if (data.unrecorded && recorded.length) {
    // The file was edited by hand since the last version: that edit is the
    // latest change, and Undo goes back to the last recorded version.
    rows.push({
      key: "unrecorded",
      label: "",
      at: "Not recorded yet",
      source: "Hand edit of the rules file",
      changed: "Recorded as a version with the next change",
      current: true,
      deleted: false,
      action: { kind: "undo", toVersion: recorded[0]!.version },
    });
  }
  recorded.forEach((v, i) => {
    const latest = i === 0 && !data.unrecorded;
    let action: VersionAction | null = null;
    if (latest) {
      const before = recorded[1]?.version ?? (data.can_undo_create ? 0 : null);
      if (before !== null) action = { kind: "undo", toVersion: before };
    } else if (!v.deleted) {
      action = { kind: "restore", toVersion: v.version };
    }
    rows.push({
      key: `v${v.version}`,
      label: `v${v.version}`,
      at: atText(v.at, timeZone),
      source: sourceLabel(v),
      changed: changedLine(v),
      current: latest,
      deleted: v.deleted,
      action,
    });
  });
  return rows;
}

/** For a rule that is gone from the rules file: the version its "Undo"
 * brings back (the one before the delete), or null when there is none. */
export function deletedUndo(data: RuleVersions): VersionAction | null {
  if (data.exists || data.unrecorded) return null;
  const [last, before] = data.versions;
  if (!last?.deleted || !before || before.deleted) return null;
  return { kind: "undo", toVersion: before.version };
}

/** The message for a refused restore. */
export function restoreError(status: number, message: string): string {
  return status === 409
    ? "This automation changed since its history was loaded. The list has been refreshed: check it, then try again."
    : `Not restored: ${message}`;
}
