/**
 * Spec 011: the Apps library's words, pure so they are unit-tested apart from
 * rendering. Tile states use the same words the shim gives app authors
 * (shim/README.md): "updated 4 min ago", "Not connected", "Can't tell", and
 * "Nothing today".
 */
import type { AppStatus, AppVersion } from "./api";
import type { SourceState } from "./protocol";

export const STATUS_WORDS: Record<AppStatus, string> = {
  approved: "Approved",
  needs_approval: "Needs approval",
  revoked: "Access revoked",
};

export const STATUS_TONE: Record<AppStatus, "good" | "warn" | "bad"> = {
  approved: "good",
  needs_approval: "warn",
  revoked: "bad",
};

/** "just now", "4 min ago", "3 h ago", "2 days ago"; "" when unreadable. */
export function ago(iso: string | null | undefined, now = Date.now()): string {
  if (!iso) return "";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "";
  const s = Math.max(0, Math.round((now - t) / 1000));
  if (s < 45) return "just now";
  const m = Math.round(s / 60);
  if (m < 60) return `${m} min ago`;
  const h = Math.round(m / 60);
  if (h < 36) return `${h} h ago`;
  const d = Math.round(h / 24);
  return `${d} ${d === 1 ? "day" : "days"} ago`;
}

/** A source's last state, in words, for the permissions list. */
export function lastStateWords(
  state: SourceState | null,
  fetchedAt: string | null,
  error: string | null,
  now = Date.now(),
): string {
  switch (state) {
    case null:
      return "Not fetched yet";
    case "fresh":
      return `Updated ${ago(fetchedAt, now)}`;
    case "empty":
      return `Nothing to show, checked ${ago(fetchedAt, now)}`;
    case "not_connected":
      return "Not connected";
    case "failed":
      return `Can't tell: ${error ?? "the last read failed"}`;
  }
}

/** Who made a version, in words. */
export function versionSource(v: Pick<AppVersion, "source" | "restored_from">) {
  if (v.source === "undo") {
    return v.restored_from != null
      ? `Restored from version ${v.restored_from}`
      : "Restored in the library";
  }
  if (v.source === "code_job") return "Built by a coding job";
  return "Changed";
}

/** What changed, in one line. */
export function versionChanged(v: Pick<AppVersion, "changed">): string {
  if (v.changed.length === 0) return "No change";
  const shown = v.changed.slice(0, 3).join(", ");
  const more = v.changed.length > 3 ? ` +${v.changed.length - 3} more` : "";
  return shown.charAt(0).toUpperCase() + shown.slice(1) + more;
}

export function atText(iso: string | null | undefined): string {
  if (!iso) return "";
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  return new Intl.DateTimeFormat("en-US", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(d);
}

/** The manifest hash as the card shows it: grouped, so it can be compared. */
export function hashGroups(hash: string): string {
  return (hash.match(/.{1,8}/g) ?? []).join(" ");
}

/** The message for a refused write. */
export function writeError(code: string, message: string): string {
  switch (code) {
    case "hash_mismatch":
      return "This app changed after this card was drawn. The card has been reloaded: check it again.";
    case "no_pending_approval":
      return "This card is no longer waiting for an answer.";
    case "stale_version":
      return "The app changed since you opened its history. Reload it and try again.";
    default:
      return message;
  }
}
