import { FilesIcon, XIcon } from "lucide-react";
import { usePathname } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import type { GroupImperativeHandle } from "react-resizable-panels";

import { ConversationEmptyState } from "@/components/ai-elements/conversation";
import { Button } from "@/components/ui/button";
import {
  ResizableHandle,
  ResizablePanel,
  ResizablePanelGroup,
} from "@/components/ui/resizable";
import { useArtifactManifests } from "@/core/artifacts/hooks";
import { panelKey, parsePanelKey } from "@/core/artifacts/store-logic";
import {
  artifactManifestValue,
  normalizeArtifactEntries,
  suppressManifestDuplicateFiles,
} from "@/core/artifacts/utils";
import {
  extractPresentFilesFromMessage,
  hasPresentFiles,
} from "@/core/messages/utils";
import { env } from "@/env";
import { useIsMobile } from "@/hooks/use-mobile";
import { cn } from "@/lib/utils";

import {
  ArtifactFileDetail,
  ArtifactFileList,
  useArtifacts,
} from "../artifacts";
import { ArtifactPanel } from "../artifacts/store/artifact-panel";
import { useThread } from "../messages/context";

const CLOSE_MODE = { chat: 100, artifacts: 0 };
const OPEN_MODE = { chat: 60, artifacts: 40 };

const ChatBox: React.FC<{ children: React.ReactNode; threadId: string }> = ({
  children,
  threadId,
}) => {
  const { thread } = useThread();
  const pathname = usePathname();
  const threadIdRef = useRef(threadId);
  const layoutRef = useRef<GroupImperativeHandle>(null);

  const {
    artifacts,
    open: artifactsOpen,
    setOpen: setArtifactsOpen,
    setArtifacts,
    select: selectArtifact,
    deselect,
    selectedArtifact,
  } = useArtifacts();
  const { manifests } = useArtifactManifests({ threadId });
  const isMobile = useIsMobile();
  // Spec 012: a store artifact opened from its card ("omni-artifact:id@n").
  const storeSelection = useMemo(
    () => parsePanelKey(selectedArtifact),
    [selectedArtifact],
  );

  const [autoSelectFirstArtifact, setAutoSelectFirstArtifact] = useState(true);
  const prevArtifactsSignatureRef = useRef("");
  const visibleArtifacts = useMemo(() => {
    const files = new Set(thread.values.artifacts ?? []);
    for (const message of thread.values.messages ?? []) {
      if (hasPresentFiles(message)) {
        for (const file of extractPresentFilesFromMessage(message)) {
          files.add(file);
        }
      }
    }
    const fileArtifacts = suppressManifestDuplicateFiles(
      Array.from(files),
      manifests,
    );
    return [
      ...manifests.map((manifest) => artifactManifestValue(manifest)),
      ...fileArtifacts,
    ];
  }, [manifests, thread.values.artifacts, thread.values.messages]);
  const normalizedVisibleArtifacts = useMemo(() => {
    return normalizeArtifactEntries(visibleArtifacts);
  }, [visibleArtifacts]);

  useEffect(() => {
    if (threadIdRef.current !== threadId) {
      threadIdRef.current = threadId;
      deselect();
    }

    // Update artifacts only when content changes to avoid a render loop.
    // normalizedVisibleArtifacts is always a new array reference, so comparing
    // the joined string prevents calling setArtifacts on every render.
    const signature = normalizedVisibleArtifacts.join("\0");
    if (signature !== prevArtifactsSignatureRef.current) {
      prevArtifactsSignatureRef.current = signature;
      setArtifacts(normalizedVisibleArtifacts);
    }

    // DO NOT automatically deselect the artifact when switching threads, because the artifacts auto discovering is not work now.
    // if (
    //   selectedArtifact &&
    //   !thread.values.artifacts?.includes(selectedArtifact)
    // ) {
    //   deselect();
    // }

    if (
      env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" &&
      autoSelectFirstArtifact
    ) {
      if (normalizedVisibleArtifacts.length > 0) {
        setAutoSelectFirstArtifact(false);
        selectArtifact(normalizedVisibleArtifacts[0]!);
      }
    }
  }, [
    threadId,
    autoSelectFirstArtifact,
    deselect,
    normalizedVisibleArtifacts,
    selectArtifact,
    selectedArtifact,
    setArtifacts,
  ]);

  const artifactPanelOpen = useMemo(() => {
    if (env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true") {
      return artifactsOpen && artifacts?.length > 0;
    }
    return artifactsOpen;
  }, [artifactsOpen, artifacts]);

  const resizableIdBase = useMemo(() => {
    return pathname.replace(/[^a-zA-Z0-9_-]+/g, "-").replace(/^-+|-+$/g, "");
  }, [pathname]);

  useEffect(() => {
    if (layoutRef.current) {
      if (artifactPanelOpen) {
        layoutRef.current.setLayout(OPEN_MODE);
      } else {
        layoutRef.current.setLayout(CLOSE_MODE);
      }
    }
  }, [artifactPanelOpen]);

  const storePanel = storeSelection ? (
    <ArtifactPanel
      key={storeSelection.id}
      id={storeSelection.id}
      version={storeSelection.version}
      mode="panel"
      onVersionChange={(n) => selectArtifact(panelKey(storeSelection.id, n))}
      onClose={() => setArtifactsOpen(false)}
    />
  ) : null;

  return (
    <>
      {/* At phone width a store artifact opens over the chat, full screen
          (the split panel would be a sliver). */}
      {isMobile &&
        artifactPanelOpen &&
        storePanel &&
        createPortal(
          <div
            className="bg-background fixed inset-0 z-50 flex flex-col overflow-hidden p-4"
            role="dialog"
            aria-modal="true"
            data-testid="artifact-panel-mobile"
          >
            {storePanel}
          </div>,
          document.body,
        )}
      <ResizablePanelGroup
        id={`${resizableIdBase}-panels`}
        orientation="horizontal"
        defaultLayout={{ chat: 100, artifacts: 0 }}
        groupRef={layoutRef}
      >
        <ResizablePanel className="relative" defaultSize={100} id="chat">
          {children}
        </ResizablePanel>
        <ResizableHandle
          id={`${resizableIdBase}-separator`}
          className={cn(
            "opacity-33 hover:opacity-100",
            !artifactPanelOpen && "pointer-events-none opacity-0",
          )}
        />
        <ResizablePanel
          className={cn(
            "transition-all duration-300 ease-in-out",
            !artifactsOpen && "opacity-0",
          )}
          id="artifacts"
        >
          <div
            className={cn(
              "h-full p-4 transition-transform duration-300 ease-in-out",
              artifactPanelOpen ? "translate-x-0" : "translate-x-full",
            )}
          >
            {storeSelection ? (
              isMobile ? null : (
                <div className="bg-background border-border size-full overflow-hidden rounded-xl border p-4">
                  {storePanel}
                </div>
              )
            ) : selectedArtifact ? (
              <ArtifactFileDetail
                className="size-full"
                filepath={selectedArtifact}
                threadId={threadId}
              />
            ) : (
              <div className="relative flex size-full justify-center">
                <div className="absolute top-1 right-1 z-30">
                  <Button
                    size="icon-sm"
                    variant="ghost"
                    onClick={() => {
                      setArtifactsOpen(false);
                    }}
                  >
                    <XIcon />
                  </Button>
                </div>
                {normalizedVisibleArtifacts.length === 0 ? (
                  <ConversationEmptyState
                    icon={<FilesIcon />}
                    title="No artifact selected"
                    description="Select an artifact to view its details"
                  />
                ) : (
                  <div className="flex size-full max-w-(--container-width-sm) flex-col justify-center p-4 pt-8">
                    <header className="shrink-0">
                      <h2 className="text-lg font-medium">Artifacts</h2>
                    </header>
                    <main className="min-h-0 grow">
                      <ArtifactFileList
                        className="max-w-(--container-width-sm) p-4 pt-12"
                        files={normalizedVisibleArtifacts}
                        threadId={threadId}
                      />
                    </main>
                  </div>
                )}
              </div>
            )}
          </div>
        </ResizablePanel>
      </ResizablePanelGroup>
    </>
  );
};

export { ChatBox };
