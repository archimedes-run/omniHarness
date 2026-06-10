import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useMemo } from "react";

import { useThread } from "@/components/workspace/messages/context";

import {
  createPreviewSession,
  createPreviewSessionFromManifest,
  loadArtifactManifests,
  loadPreviewSessionLogs,
  loadPreviewSessions,
  loadProjectFileContent,
  loadProjectFiles,
  loadWorkspaceFileContent,
  loadWorkspaceFiles,
  restartPreviewSession,
  stopPreviewSession,
} from "./api";
import { loadArtifactContent, loadArtifactContentFromToolCall } from "./loader";

export function useArtifactContent({
  filepath,
  threadId,
  enabled,
}: {
  filepath: string;
  threadId: string;
  enabled?: boolean;
}) {
  const isWriteFile = useMemo(() => {
    return filepath.startsWith("write-file:");
  }, [filepath]);
  const { thread, isMock } = useThread();
  const content = useMemo(() => {
    if (isWriteFile) {
      return loadArtifactContentFromToolCall({ url: filepath, thread });
    }
    return null;
  }, [filepath, isWriteFile, thread]);

  const { data, isLoading, error } = useQuery({
    queryKey: ["artifact", filepath, threadId, isMock],
    queryFn: () => {
      return loadArtifactContent({ filepath, threadId, isMock });
    },
    enabled,
    // Cache artifact content for 5 minutes to avoid repeated fetches (especially for .skill ZIP extraction)
    staleTime: 5 * 60 * 1000,
  });
  return {
    content: isWriteFile ? content : data?.content,
    url: isWriteFile ? undefined : data?.url,
    isLoading,
    error,
  };
}

export function useArtifactManifests({ threadId }: { threadId: string }) {
  const { isMock } = useThread();
  const { data, isLoading, error } = useQuery({
    queryKey: ["artifact-manifests", threadId, isMock],
    queryFn: () => loadArtifactManifests({ threadId, isMock }),
    staleTime: 30 * 1000,
  });

  return {
    manifests: data?.manifests ?? [],
    isLoading,
    error,
  };
}

export function usePreviewSessions({
  threadId,
  enabled = true,
}: {
  threadId: string;
  enabled?: boolean;
}) {
  const { isMock } = useThread();
  const { data, isLoading, error } = useQuery({
    queryKey: ["preview-sessions", threadId],
    queryFn: () => loadPreviewSessions({ threadId }),
    enabled: enabled && !isMock,
    refetchInterval: (query) => {
      const sessions = query.state.data ?? [];
      return sessions.some(
        (session) =>
          session.status === "starting" || session.status === "running",
      )
        ? 3000
        : false;
    },
  });

  return {
    previews: data ?? [],
    isLoading,
    error,
  };
}

export function useCreatePreviewSession({ threadId }: { threadId: string }) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createPreviewSession,
    onSuccess() {
      void queryClient.invalidateQueries({
        queryKey: ["preview-sessions", threadId],
      });
    },
  });
}

export function useCreatePreviewFromManifest({
  threadId,
}: {
  threadId: string;
}) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: createPreviewSessionFromManifest,
    onSuccess() {
      void queryClient.invalidateQueries({
        queryKey: ["preview-sessions", threadId],
      });
    },
  });
}

export function useStopPreviewSession({ threadId }: { threadId: string }) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: stopPreviewSession,
    onSuccess() {
      void queryClient.invalidateQueries({
        queryKey: ["preview-sessions", threadId],
      });
    },
  });
}

export function useRestartPreviewSession({ threadId }: { threadId: string }) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: restartPreviewSession,
    onSuccess() {
      void queryClient.invalidateQueries({
        queryKey: ["preview-sessions", threadId],
      });
    },
  });
}

export function usePreviewSessionLogs({
  threadId,
  previewId,
  enabled = true,
}: {
  threadId: string;
  previewId?: string;
  enabled?: boolean;
}) {
  const { isMock } = useThread();
  const { data, isLoading, error } = useQuery({
    queryKey: ["preview-session-logs", threadId, previewId],
    queryFn: () => loadPreviewSessionLogs({ threadId, previewId: previewId! }),
    enabled: enabled && !isMock && Boolean(previewId),
    retry: false,
    refetchInterval: (query) => {
      if (query.state.error) return false;
      const status = query.state.data?.status;
      if (status === "stopped" || status === "failed") return false;
      return 3000;
    },
  });

  return {
    logs: data,
    isLoading,
    error,
  };
}

export function useProjectFiles({
  threadId,
  artifactId,
  enabled = true,
}: {
  threadId: string;
  artifactId: string;
  enabled?: boolean;
}) {
  const { isMock } = useThread();
  const { data, isLoading, error } = useQuery({
    queryKey: ["project-files", threadId, artifactId],
    queryFn: () => loadProjectFiles({ threadId, artifactId }),
    enabled: enabled && !isMock,
    staleTime: 30 * 1000,
    refetchInterval: 3 * 1000,
  });

  return {
    files: data?.files ?? [],
    root: data?.root,
    isLoading,
    error,
  };
}

export function useProjectFileContent({
  threadId,
  artifactId,
  path,
  enabled = true,
}: {
  threadId: string;
  artifactId: string;
  path?: string;
  enabled?: boolean;
}) {
  const { isMock } = useThread();
  const { data, isLoading, error } = useQuery({
    queryKey: ["project-file-content", threadId, artifactId, path],
    queryFn: () =>
      loadProjectFileContent({ threadId, artifactId, path: path! }),
    enabled: enabled && !isMock && Boolean(path),
    staleTime: 30 * 1000,
  });

  return {
    content: data,
    isLoading,
    error,
  };
}

export function useWorkspaceFiles({
  threadId,
  root,
  enabled = true,
}: {
  threadId: string;
  root: string;
  enabled?: boolean;
}) {
  const { isMock } = useThread();
  const { data, isLoading, error } = useQuery({
    queryKey: ["workspace-files", threadId, root],
    queryFn: () => loadWorkspaceFiles({ threadId, root }),
    enabled: enabled && !isMock && Boolean(root),
    staleTime: 5 * 1000,
    refetchInterval: 3 * 1000,
  });

  return {
    files: data?.files ?? [],
    root: data?.root,
    isLoading,
    error,
  };
}

export function useWorkspaceFileContent({
  threadId,
  root,
  path,
  enabled = true,
}: {
  threadId: string;
  root: string;
  path?: string;
  enabled?: boolean;
}) {
  const { isMock } = useThread();
  const { data, isLoading, error } = useQuery({
    queryKey: ["workspace-file-content", threadId, root, path],
    queryFn: () => loadWorkspaceFileContent({ threadId, root, path: path! }),
    enabled: enabled && !isMock && Boolean(path) && Boolean(root),
    staleTime: 10 * 1000,
  });

  return {
    content: data,
    isLoading,
    error,
  };
}
