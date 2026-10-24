"use client";

import "./studio.css";

import { XIcon } from "lucide-react";
import { useSearchParams } from "next/navigation";
import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";

import type { CloseGuard } from "@/components/workspace/shell/panels";
import { urlWithPanel } from "@/components/workspace/shell/panels";

import { AgentWizard } from "./agent-wizard";
import { AgentsList } from "./agents-list";
import { useStudioCopy } from "./copy";
import { SkillWizard } from "./skill-wizard";
import { SkillsList } from "./skills-list";
import { ITEM_PARAM, readItemParam, writeItemParam } from "./url-item";

export type StudioKind = "agents" | "skills";

export type Route =
  | { view: "agents" }
  | { view: "skills" }
  /** id null: a new one. `step`/`panel`: where it opens. */
  | {
      view: "agent";
      id: string | null;
      step?: number;
      panel?: string;
      sentence?: string;
    }
  | { view: "skill"; id: string | null; step?: number };

/** What an open editor answers to the Studio. */
export interface EditorHandle {
  /** Esc: close an inner editor or picker first. True when it did. */
  escape: () => boolean;
  /** Leave the editor: `then` runs now when nothing is unsaved, else after the
   * person discards or saves on the prompt. */
  requestLeave: (then: () => void) => void;
  dirty: () => boolean;
}

interface StudioApi {
  go: (route: Route) => void;
  close: () => void;
  toast: (text: string, undo?: () => void) => void;
  switchTo: (kind: StudioKind) => void;
  registerEditor: (handle: EditorHandle | null) => void;
}

const StudioContext = createContext<StudioApi | null>(null);

export function useStudio(): StudioApi {
  const api = useContext(StudioContext);
  if (!api) throw new Error("useStudio outside the Studio");
  return api;
}

function initialRoute(kind: StudioKind): Route {
  const item = readItemParam();
  if (!item) return { view: kind };
  if (kind === "agents")
    return { view: "agent", id: item === "new" ? null : item };
  return { view: "skill", id: item === "new" ? null : item };
}

function itemOf(route: Route): string | null {
  if (route.view === "agent" || route.view === "skill")
    return route.id ?? "new";
  return null;
}

/**
 * The Agent & Skill Studio (006-G): one modal for both panels. A list of
 * cards (Agents | Skills), and a four-step editor for each (agents: Setup,
 * Configuration, Schedule, Notifications; skills: Details, Instructions,
 * Files, Test). The item shown is in the URL (`?item=`), so a copied link
 * opens on it.
 */
export function Studio({
  kind,
  onClose,
  setCloseGuard,
}: {
  kind: StudioKind;
  onClose: () => void;
  setCloseGuard: (guard: CloseGuard | null) => void;
}) {
  const c = useStudioCopy();
  const [route, setRoute] = useState<Route>(() => initialRoute(kind));
  const editor = useRef<EditorHandle | null>(null);
  const [toast, setToast] = useState<{
    text: string;
    undo?: () => void;
    n: number;
  } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const routeRef = useRef(route);
  routeRef.current = route;

  const inEditor = route.view === "agent" || route.view === "skill";

  const leaveThen = useCallback((then: () => void) => {
    const handle = editor.current;
    const r = routeRef.current;
    if ((r.view === "agent" || r.view === "skill") && handle)
      handle.requestLeave(then);
    else then();
  }, []);

  const go = useCallback(
    (next: Route) => {
      const r = routeRef.current;
      const leaving =
        (r.view === "agent" || r.view === "skill") &&
        (next.view !== r.view || ("id" in next && next.id !== r.id));
      if (leaving) leaveThen(() => setRoute(next));
      else setRoute(next);
    },
    [leaveThen],
  );

  const close = useCallback(() => leaveThen(onClose), [leaveThen, onClose]);

  const switchTo = useCallback(
    (target: StudioKind) =>
      leaveThen(() => {
        setRoute({ view: target });
        const url = new URL(urlWithPanel(target), window.location.origin);
        url.searchParams.delete(ITEM_PARAM);
        window.history.replaceState(
          null,
          "",
          `${url.pathname}${url.search}${url.hash}`,
        );
      }),
    [leaveThen],
  );

  const showToast = useCallback((text: string, undo?: () => void) => {
    if (timer.current) clearTimeout(timer.current);
    setToast({ text, undo, n: Date.now() });
    timer.current = setTimeout(() => setToast(null), 6000);
  }, []);
  useEffect(
    () => () => void (timer.current && clearTimeout(timer.current)),
    [],
  );

  const api = useMemo<StudioApi>(
    () => ({
      go,
      close,
      toast: showToast,
      switchTo,
      registerEditor: (handle) => {
        editor.current = handle;
      },
    }),
    [go, close, showToast, switchTo],
  );

  // Esc and a click outside ask the Studio first (PanelSheet's guard).
  useEffect(() => {
    setCloseGuard((reason) => {
      const r = routeRef.current;
      if (r.view !== "agent" && r.view !== "skill") return false;
      const handle = editor.current;
      if (reason === "escape") {
        if (handle?.escape()) return true;
        leaveThen(() =>
          setRoute({ view: r.view === "agent" ? "agents" : "skills" }),
        );
        return true;
      }
      if (handle?.dirty()) {
        handle.requestLeave(onClose);
        return true;
      }
      return false;
    });
    return () => setCloseGuard(null);
  }, [setCloseGuard, leaveThen, onClose]);

  // The panel the sheet shows changed (the capsule, or our own switch).
  useEffect(() => {
    const r = routeRef.current;
    const showing: StudioKind =
      r.view === "agent" || r.view === "agents" ? "agents" : "skills";
    if (showing !== kind) leaveThen(() => setRoute({ view: kind }));
  }, [kind, leaveThen]);

  // "+ New agent" asked for from outside while the panel is open.
  const itemParam = useSearchParams().get(ITEM_PARAM);
  useEffect(() => {
    if (itemParam !== "new") return;
    const r = routeRef.current;
    if (kind === "agents" && !(r.view === "agent" && r.id === null))
      go({ view: "agent", id: null });
    if (kind === "skills" && !(r.view === "skill" && r.id === null))
      go({ view: "skill", id: null });
  }, [itemParam, kind, go]);

  useEffect(() => writeItemParam(itemOf(route)), [route]);
  useEffect(() => () => writeItemParam(null), []);

  let body: ReactNode;
  if (route.view === "agents") body = <AgentsList />;
  else if (route.view === "skills") body = <SkillsList />;
  else if (route.view === "agent")
    body = (
      <AgentWizard
        key={`agent:${route.id ?? "new"}`}
        id={route.id}
        initialStep={route.step}
        initialPanel={route.panel}
        initialSentence={route.sentence}
      />
    );
  else
    body = (
      <SkillWizard
        key={`skill:${route.id ?? "new"}`}
        id={route.id}
        initialStep={route.step}
      />
    );

  return (
    <StudioContext.Provider value={api}>
      <div
        className="oh-studio"
        data-testid="studio"
        data-view={route.view}
        data-editor={inEditor ? "1" : undefined}
      >
        {body}
        {toast ? (
          <div
            className="toast"
            role="status"
            data-testid="studio-toast"
            key={toast.n}
          >
            {toast.text}
            {toast.undo ? (
              <button
                type="button"
                onClick={() => {
                  toast.undo?.();
                  setToast(null);
                }}
              >
                {c.undo}
              </button>
            ) : null}
            <button
              type="button"
              className="icon-btn"
              style={{ color: "inherit", width: 24, height: 24 }}
              aria-label={c.dismiss}
              onClick={() => setToast(null)}
            >
              <XIcon size={14} aria-hidden />
            </button>
          </div>
        ) : null}
      </div>
    </StudioContext.Provider>
  );
}

/** The list views' header: icon, title, Agents | Skills, close. */
export function ListHead({
  which,
  title,
  subtitle,
  icon,
}: {
  which: StudioKind;
  title: string;
  subtitle: string;
  icon: ReactNode;
}) {
  const studio = useStudio();
  return (
    <header className="m-head">
      <div className="m-head-row">
        <span className="m-title-ico" aria-hidden>
          {icon}
        </span>
        <div className="grow">
          <h2 className="m-title" id="studio-title">
            {title}
          </h2>
          <p className="m-sub">{subtitle}</p>
        </div>
        <SwitchNav which={which} onSwitch={studio.switchTo} />
        <CloseButton />
      </div>
    </header>
  );
}

export function SwitchNav({
  which,
  onSwitch,
}: {
  which: StudioKind;
  onSwitch: (k: StudioKind) => void;
}) {
  const c = useStudioCopy();
  return (
    <nav className="switcher" aria-label={c.switcher}>
      {(["agents", "skills"] as const).map((k) => (
        <button
          key={k}
          type="button"
          aria-current={which === k ? "page" : undefined}
          onClick={() => (which === k ? undefined : onSwitch(k))}
          data-testid={`studio-switch-${k}`}
        >
          {k === "agents" ? c.agentsTab : c.skillsTab}
        </button>
      ))}
    </nav>
  );
}

export function CloseButton() {
  const c = useStudioCopy();
  const studio = useStudio();
  return (
    <button
      type="button"
      className="icon-btn"
      aria-label={c.close}
      onClick={studio.close}
      data-testid="panel-close"
    >
      <XIcon size={18} aria-hidden />
    </button>
  );
}
