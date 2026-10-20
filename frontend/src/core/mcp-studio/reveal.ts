import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

/** What the person sees when a reveal is refused, by the gateway's status. */
export function revealRefusal(status: number, detail: string | null): string {
  switch (status) {
    case 403:
      return "That password is not right.";
    case 429:
      return "Too many wrong passwords. Try again in a few minutes.";
    case 400:
      // An account with no password: the gateway says why in words.
      return detail ?? "This value cannot be revealed for this account.";
    case 404:
      return "There is no stored value to reveal.";
    default:
      return `Could not reveal the value (${status}).`;
  }
}

export type RevealResult =
  | { ok: true; value: string }
  | { ok: false; message: string };

/**
 * Reveal one stored secret. The password goes in the JSON body, never the
 * URL; the gateway checks it and logs the key name (never the value).
 */
export async function revealSecret(
  serverId: string,
  keyName: string,
  password: string,
): Promise<RevealResult> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/mcp-studio/servers/${encodeURIComponent(serverId)}/secrets/reveal`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ key_name: keyName, password }),
    },
  );
  if (!response.ok) {
    let detail: string | null = null;
    try {
      const body = (await response.json()) as { detail?: unknown };
      if (typeof body.detail === "string") detail = body.detail;
    } catch {
      // the status is all there is
    }
    return { ok: false, message: revealRefusal(response.status, detail) };
  }
  const body = (await response.json()) as { values: Record<string, string> };
  const value = body.values[keyName];
  return value === undefined
    ? { ok: false, message: revealRefusal(404, null) }
    : { ok: true, value };
}
