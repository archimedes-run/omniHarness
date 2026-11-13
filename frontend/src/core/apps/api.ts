/**
 * Spec 011: the gateway's Apps routes (specs/011-apps/api.md). Every call is
 * the owner's own session from this page; writes carry the CSRF header (the
 * shared fetch wrapper adds it). The app frame never calls any of these.
 */
import { fetch } from "@/core/api/fetcher";
import { getBackendBaseURL } from "@/core/config";

import type { SourceResult, SourceState } from "./protocol";

export type AppStatus = "approved" | "needs_approval" | "revoked";

export interface AppSummary {
  id: string;
  name: string;
  description: string;
  current_version: number;
  manifest_hash: string;
  status: AppStatus;
  pinned: boolean;
  updated_at: string;
  last_opened_at: string | null;
}

export interface SourceView {
  name: string;
  use: string;
  words: string;
  fields: string[];
  params: Record<string, unknown>;
  refresh_s: number;
  refresh_words: string;
  link_hosts: string[];
  last_fetched_at: string | null;
  last_state: SourceState | null;
  last_error: string | null;
}

export interface ApprovalCard {
  id: string;
  app_id: string;
  app_name: string;
  version: number;
  manifest_hash: string;
  status: "pending" | "approved" | "superseded";
  sources: { name: string; words: string; refresh_words: string }[];
  sentence: string;
  suggestion: boolean;
  suggestion_source: string | null;
  thread_id: string | null;
  created_at: string;
  resolved_at: string | null;
}

export interface AppDetail extends AppSummary {
  html_url: string;
  sources: SourceView[];
  approval: ApprovalCard | null;
}

export interface AppVersion {
  version: number;
  at: string;
  who: string;
  source: "code_job" | "undo" | string;
  changed: string[];
  manifest_hash: string;
  approved: boolean;
  restored_from: number | null;
}

export interface AppVersions {
  current: number;
  versions: AppVersion[];
}

export interface Grant {
  manifest_hash: string;
  approved_at: string;
  revoked_at: string | null;
  version: number | null;
}

export interface AppPermissions {
  app_id: string;
  version: number;
  manifest_hash: string;
  status: AppStatus;
  sentence: string;
  sources: SourceView[];
  grants: Grant[];
  /** The app's last audit entries, newest first: events and ids, no data. */
  activity?: { at: string; event: string; detail?: Record<string, unknown> }[];
}

export interface CatalogEntry {
  id: string;
  kind: "connector" | "first_party" | string;
  toolkit?: string | null;
  fields: string[];
  params: Record<string, unknown>;
  link_hosts: string[];
  default_refresh_s: number;
}

export interface BatchData {
  app_id: string;
  version: number;
  results: Record<string, SourceResult>;
}

/** A gateway refusal with its stable code (api.md "Error codes"). */
export class AppsApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code: string,
  ) {
    super(message);
  }
}

const base = () => `${getBackendBaseURL()}/api/apps`;

async function read<T>(response: Response): Promise<T> {
  if (response.ok) {
    return response.status === 204
      ? (undefined as T)
      : ((await response.json()) as T);
  }
  let code = "error";
  let message = `The gateway answered ${response.status}.`;
  try {
    const body = (await response.json()) as {
      detail?: { code?: string; message?: string } | string;
    };
    if (typeof body.detail === "string") message = body.detail;
    else if (body.detail) {
      code = body.detail.code ?? code;
      message = body.detail.message ?? message;
    }
  } catch {
    // Not JSON: keep the status line.
  }
  throw new AppsApiError(message, response.status, code);
}

const enc = encodeURIComponent;

function send(path: string, method: "POST" | "PUT", body?: unknown) {
  return fetch(path, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
}

export async function listApps(): Promise<AppSummary[]> {
  const body = await read<{ apps: AppSummary[] }>(await fetch(base()));
  return body.apps;
}

export async function getApp(id: string): Promise<AppDetail> {
  return read(await fetch(`${base()}/${enc(id)}`));
}

export async function getAppData(id: string): Promise<BatchData> {
  return read(await fetch(`${base()}/${enc(id)}/data`));
}

export async function getAppSource(
  id: string,
  source: string,
  refresh = false,
): Promise<SourceResult> {
  return read(
    await fetch(
      `${base()}/${enc(id)}/data/${enc(source)}${refresh ? "?refresh=1" : ""}`,
    ),
  );
}

export async function getAppVersions(id: string): Promise<AppVersions> {
  return read(await fetch(`${base()}/${enc(id)}/versions`));
}

export async function restoreApp(
  id: string,
  toVersion: number,
  baseVersion: number,
): Promise<AppDetail> {
  return read(
    await send(`${base()}/${enc(id)}/restore`, "POST", {
      to_version: toVersion,
      base_version: baseVersion,
    }),
  );
}

export async function getAppPermissions(id: string): Promise<AppPermissions> {
  return read(await fetch(`${base()}/${enc(id)}/permissions`));
}

export async function revokeApp(id: string): Promise<{
  status: string;
  grants_ended: number;
  cache_rows_deleted: number;
}> {
  return read(await send(`${base()}/${enc(id)}/revoke`, "POST"));
}

export async function getPendingApproval(
  id: string,
): Promise<ApprovalCard | null> {
  try {
    return await read<ApprovalCard>(
      await fetch(`${base()}/${enc(id)}/approval`),
    );
  } catch (err) {
    if (err instanceof AppsApiError && err.code === "no_pending_approval") {
      return null;
    }
    throw err;
  }
}

export async function listThreadApprovals(
  threadId: string,
): Promise<ApprovalCard[]> {
  const body = await read<{ cards: ApprovalCard[] }>(
    await fetch(`${base()}/approvals?thread_id=${enc(threadId)}`),
  );
  return body.cards;
}

/** The card's own button press: the hash it showed, and its id (FR-006). */
export async function approveApp(
  id: string,
  manifestHash: string,
  cardId: string,
): Promise<{ status: string; manifest_hash: string; approved_at: string }> {
  return read(
    await send(`${base()}/${enc(id)}/approve`, "POST", {
      manifest_hash: manifestHash,
      card_id: cardId,
    }),
  );
}

/** FR-022: a frame message the host dropped, for the apps audit. */
export async function reportRefusedMessage(
  id: string,
  refusal: { reason: string; type?: string; source?: string },
): Promise<void> {
  const body: Record<string, string> = { reason: refusal.reason.slice(0, 120) };
  if (refusal.type) body.type = refusal.type.slice(0, 32);
  if (refusal.source) body.source = refusal.source.slice(0, 64);
  await read<void>(await send(`${base()}/${enc(id)}/refused`, "POST", body));
}

export async function getCatalog(): Promise<CatalogEntry[]> {
  const body = await read<{ entries: CatalogEntry[] }>(
    await fetch(`${base()}/catalog`),
  );
  return body.entries;
}

const pinsPath = () => `${getBackendBaseURL()}/api/preferences/app-pins`;

export async function getAppPins(): Promise<string[]> {
  const body = await read<{ pins: string[] }>(await fetch(pinsPath()));
  return body.pins;
}

export async function saveAppPins(pins: string[]): Promise<string[]> {
  const body = await read<{ pins: string[] }>(
    await send(pinsPath(), "PUT", { pins }),
  );
  return body.pins;
}
