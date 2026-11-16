import {
  createContext,
  useCallback,
  useContext,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import { useSidebar } from "@/components/ui/sidebar";
import { env } from "@/env";

export interface BuildPreviewDetails {
  threadId: string;
  title: string;
  sample: boolean;
  appId?: string;
}

export interface ArtifactsContextType {
  buildPreviews: Record<string, BuildPreviewDetails>;
  registerBuildPreview: (path: string, details: BuildPreviewDetails) => void;
  artifacts: string[];
  setArtifacts: (artifacts: string[]) => void;

  selectedArtifact: string | null;
  autoSelect: boolean;
  select: (artifact: string, autoSelect?: boolean) => void;
  deselect: () => void;

  open: boolean;
  autoOpen: boolean;
  setOpen: (open: boolean) => void;
}

const ArtifactsContext = createContext<ArtifactsContextType | undefined>(
  undefined,
);

interface ArtifactsProviderProps {
  children: ReactNode;
}

export function ArtifactsProvider({ children }: ArtifactsProviderProps) {
  const [buildPreviews, setBuildPreviews] = useState<
    Record<string, BuildPreviewDetails>
  >({});
  const registerBuildPreview = useCallback(
    (path: string, details: BuildPreviewDetails) => {
      setBuildPreviews((previous) => {
        if (JSON.stringify(previous[path]) === JSON.stringify(details))
          return previous;
        return { ...previous, [path]: details };
      });
    },
    [],
  );
  const [artifacts, setArtifacts] = useState<string[]>([]);
  const [selectedArtifact, setSelectedArtifact] = useState<string | null>(null);
  const [autoSelect, setAutoSelect] = useState(true);
  const [open, setOpen] = useState(
    env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true",
  );
  const [autoOpen, setAutoOpen] = useState(true);
  const { setOpen: setSidebarOpen } = useSidebar();

  const select = useCallback(
    (artifact: string, autoSelect = false) => {
      setSelectedArtifact(artifact);
      if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY !== "true") {
        setSidebarOpen(false);
      }
      if (!autoSelect) {
        setAutoSelect(false);
      }
    },
    [setSidebarOpen, setSelectedArtifact, setAutoSelect],
  );

  const deselect = useCallback(() => {
    setSelectedArtifact(null);
    setAutoSelect(true);
    setOpen(false);
  }, []);

  const autoOpenRef = useRef(autoOpen);
  autoOpenRef.current = autoOpen;
  const handleSetOpen = useCallback((isOpen: boolean) => {
    if (!isOpen && autoOpenRef.current) {
      setAutoOpen(false);
      setAutoSelect(false);
    }
    setOpen(isOpen);
  }, []);

  const value = useMemo<ArtifactsContextType>(
    () => ({
      artifacts,
      setArtifacts,
      buildPreviews,
      registerBuildPreview,
      open,
      autoOpen,
      autoSelect,
      setOpen: handleSetOpen,
      selectedArtifact,
      select,
      deselect,
    }),
    [
      artifacts,
      setArtifacts,
      buildPreviews,
      registerBuildPreview,
      open,
      autoOpen,
      autoSelect,
      handleSetOpen,
      selectedArtifact,
      select,
      deselect,
    ],
  );

  return (
    <ArtifactsContext.Provider value={value}>
      {children}
    </ArtifactsContext.Provider>
  );
}

export function useArtifacts() {
  const context = useContext(ArtifactsContext);
  if (context === undefined) {
    throw new Error("useArtifacts must be used within an ArtifactsProvider");
  }
  return context;
}
