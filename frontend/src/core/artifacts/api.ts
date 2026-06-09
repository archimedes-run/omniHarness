import { fetch } from "../api/fetcher";
import { getBackendBaseURL } from "../config";

export interface ArtifactManifest {
  id: string;
  title: string;
  type: "static_site" | "web_app";
  entrypoint?: string | null;
  root: string;
  source_path?: string | null;
  preview:
    | {
        mode: "static";
      }
    | {
        mode: "dev_server";
        command: string;
        port?: number | null;
      };
  created_by?: string | null;
  manifest_path: string;
  root_path: string;
  entrypoint_path?: string | null;
}

export interface ArtifactManifestListResponse {
  manifests: ArtifactManifest[];
}

export interface PreviewSession {
  id: string;
  user_id: string;
  thread_id: string;
  artifact_id: string;
  root_path: string;
  command: string;
  port?: number | null;
  status: "starting" | "running" | "failed" | "stopped";
  proxy_url: string;
  logs_url: string;
  created_at: string;
  updated_at: string;
  expires_at: string;
  exit_code?: number | null;
  error?: string | null;
}

export interface PreviewSessionLogsResponse {
  preview_id: string;
  thread_id: string;
  status: "starting" | "running" | "failed" | "stopped";
  logs: string;
  exit_code?: number | null;
  error?: string | null;
}

export async function loadArtifactManifests({
  threadId,
  isMock,
}: {
  threadId: string;
  isMock?: boolean;
}): Promise<ArtifactManifestListResponse> {
  if (isMock) {
    return { manifests: [] };
  }

  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/artifacts/manifests`,
  );
  if (!response.ok) {
    throw new Error(`Failed to load artifact manifests: ${response.status}`);
  }
  return response.json() as Promise<ArtifactManifestListResponse>;
}

export async function loadPreviewSessions({
  threadId,
}: {
  threadId: string;
}): Promise<PreviewSession[]> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/previews`,
  );
  if (!response.ok) {
    throw new Error(`Failed to load preview sessions: ${response.status}`);
  }
  return response.json() as Promise<PreviewSession[]>;
}

export async function createPreviewSession({
  threadId,
  artifactId,
  rootPath,
  command,
  port,
}: {
  threadId: string;
  artifactId: string;
  rootPath: string;
  command: string;
  port?: number | null;
}): Promise<PreviewSession> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/previews`,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        artifact_id: artifactId,
        root_path: rootPath,
        command,
        port: port ?? undefined,
      }),
    },
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({
      detail: `Failed to create preview session: ${response.status}`,
    }));
    throw new Error(error.detail ?? "Failed to create preview session");
  }
  return response.json() as Promise<PreviewSession>;
}

export async function stopPreviewSession({
  threadId,
  previewId,
}: {
  threadId: string;
  previewId: string;
}): Promise<PreviewSession> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/previews/${previewId}/stop`,
    {
      method: "POST",
    },
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({
      detail: `Failed to stop preview session: ${response.status}`,
    }));
    throw new Error(error.detail ?? "Failed to stop preview session");
  }
  return response.json() as Promise<PreviewSession>;
}

export async function restartPreviewSession({
  threadId,
  previewId,
}: {
  threadId: string;
  previewId: string;
}): Promise<PreviewSession> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/previews/${previewId}/restart`,
    {
      method: "POST",
    },
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({
      detail: `Failed to restart preview session: ${response.status}`,
    }));
    throw new Error(error.detail ?? "Failed to restart preview session");
  }
  return response.json() as Promise<PreviewSession>;
}

export async function createPreviewSessionFromManifest({
  threadId,
  artifactId,
}: {
  threadId: string;
  artifactId: string;
}): Promise<PreviewSession> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/artifacts/manifests/${artifactId}/preview`,
    {
      method: "POST",
    },
  );
  if (!response.ok) {
    const error = await response.json().catch(() => ({
      detail: `Failed to create preview session: ${response.status}`,
    }));
    throw new Error(error.detail ?? "Failed to create preview session");
  }
  return response.json() as Promise<PreviewSession>;
}

export async function loadPreviewSessionLogs({
  threadId,
  previewId,
}: {
  threadId: string;
  previewId: string;
}): Promise<PreviewSessionLogsResponse> {
  const response = await fetch(
    `${getBackendBaseURL()}/api/threads/${threadId}/previews/${previewId}/logs`,
  );
  if (!response.ok) {
    throw new Error(`Failed to load preview logs: ${response.status}`);
  }
  return response.json() as Promise<PreviewSessionLogsResponse>;
}
