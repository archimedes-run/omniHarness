"use client";

import {
  CheckIcon,
  ChevronLeftIcon,
  ChevronRightIcon,
  InfoIcon,
  SparklesIcon,
  UserIcon,
} from "lucide-react";
import { useEffect, useRef, type ReactNode } from "react";

import { useStudioCopy } from "./copy";
import { Kbd, cx } from "./parts";
import { CloseButton } from "./studio";

export interface StepState {
  label: string;
  /** Has unsaved changes (edit mode). */
  dirty: boolean;
  /** Filled by a one-sentence draft (new agents). */
  drafted: boolean;
}

/**
 * The editor frame both steppers share (design: 03-18): breadcrumb, the
 * item's face and name, a four-step progress bar you can jump along, the
 * step's content, an unsaved-changes prompt, and the footer.
 */
export function WizardShell({
  kind,
  backLabel,
  onBack,
  isNew,
  step,
  reached,
  steps,
  onStep,
  identity,
  title,
  badges,
  subtitle,
  dirty,
  leaving,
  children,
  footer,
  testId,
  history,
}: {
  kind: string;
  backLabel: string;
  onBack: () => void;
  isNew: boolean;
  step: number;
  /** The furthest step a NEW item may jump to. */
  reached: number;
  steps: StepState[];
  onStep: (n: number) => void;
  identity: ReactNode;
  title: string;
  badges: ReactNode;
  subtitle: string;
  dirty: boolean;
  leaving: {
    steps: string[];
    onKeep: () => void;
    onDiscard: () => void;
    onSave: () => void;
    saving: boolean;
  } | null;
  children: ReactNode;
  footer: ReactNode;
  testId: string;
  /** The version history button, for a saved item. */
  history?: ReactNode;
}) {
  const c = useStudioCopy();
  const body = useRef<HTMLDivElement>(null);
  // A new step starts at its top.
  useEffect(() => {
    body.current?.scrollTo({ top: 0 });
  }, [step]);
  return (
    <div className="contents" data-testid={testId} data-step={step}>
      <header className="m-head">
        <div className="m-head-row">
          <button
            type="button"
            className="crumb"
            onClick={onBack}
            data-testid="wizard-back-list"
          >
            <ChevronLeftIcon size={16} aria-hidden />
            {backLabel}
          </button>
          <span className="eyebrow">{c.eyebrow(isNew, kind, step)}</span>
          <span className="grow" />
          {history}
          <span className="owner" title={c.ownerTitle(kind)}>
            <span className="who">
              <UserIcon size={12} aria-hidden />
            </span>
            {c.owner}
          </span>
          <CloseButton />
        </div>
        <div className="head-id">
          {identity}
          <div className="grow">
            <div className="row wrap" style={{ gap: 10 }}>
              <h2
                className="nm"
                id="studio-title"
                style={{ margin: 0 }}
                data-testid="wizard-title"
              >
                {title}
              </h2>
              {badges}
              {dirty ? (
                <span className="unsaved" data-testid="wizard-unsaved">
                  <span className="dirty-dot" />
                  {c.unsavedChanges}
                </span>
              ) : null}
            </div>
            <div className="m-sub" style={{ marginTop: 2 }}>
              {subtitle}
            </div>
          </div>
        </div>
        <nav aria-label={c.stepsNav(kind)}>
          <ol className="steps">
            {steps.map((s, i) => {
              const n = i + 1;
              const current = step === n;
              const done = isNew ? n < step : !current;
              const reachable = !isNew || n <= reached;
              return (
                <li key={s.label}>
                  <button
                    type="button"
                    className={cx(
                      "step",
                      current && "current",
                      done && !current && "done",
                    )}
                    aria-current={current ? "step" : undefined}
                    aria-disabled={reachable ? undefined : true}
                    aria-label={c.stepAria(n, s.label, s.dirty)}
                    onClick={() => (reachable ? onStep(n) : undefined)}
                    data-testid={`wizard-step-${n}`}
                    data-dirty={s.dirty ? "1" : undefined}
                  >
                    <span className="bar">
                      {current || done ? <i /> : null}
                    </span>
                    <span className="lbl">
                      <span className="num">
                        {done && !current ? (
                          <CheckIcon size={12} aria-hidden />
                        ) : (
                          n
                        )}
                      </span>
                      <span className="txt">{s.label}</span>
                      <span className="sub">
                        {s.dirty ? (
                          <>
                            <span className="dirty-dot" aria-hidden />
                            {c.edited}
                          </>
                        ) : s.drafted ? (
                          <>
                            <SparklesIcon size={11} aria-hidden />
                            {c.drafted}
                          </>
                        ) : null}
                      </span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ol>
        </nav>
      </header>
      <div
        ref={body}
        className="m-body"
        style={{ borderTop: "1px solid var(--border)" }}
        data-testid="wizard-body"
      >
        {children}
      </div>
      {leaving ? (
        <div
          className="confirm-bar"
          role="alertdialog"
          aria-label={c.unsavedChanges}
          data-testid="leave-bar"
        >
          <InfoIcon size={16} aria-hidden />
          <span className="grow">{c.leave.body(c.and(leaving.steps))}</span>
          <button
            type="button"
            className="btn sm ghost"
            onClick={leaving.onKeep}
            autoFocus
          >
            {c.leave.keep}
          </button>
          <button
            type="button"
            className="btn sm"
            onClick={leaving.onDiscard}
            data-testid="leave-discard"
          >
            {c.leave.discard}
          </button>
          <button
            type="button"
            className="btn sm solid"
            onClick={leaving.onSave}
            disabled={leaving.saving}
            data-testid="leave-save"
          >
            {c.leave.saveClose}
          </button>
        </div>
      ) : null}
      <footer className="m-foot">{footer}</footer>
    </div>
  );
}

/** The footer's left side: Back, Cancel and the shortcut hint. */
export function FootLeft({
  step,
  onPrev,
  onCancel,
  dirty,
}: {
  step: number;
  onPrev: () => void;
  onCancel: () => void;
  dirty: boolean;
}) {
  const c = useStudioCopy();
  return (
    <>
      {step > 1 ? (
        <button
          type="button"
          className="btn"
          onClick={onPrev}
          data-testid="wizard-prev"
        >
          <ChevronLeftIcon size={16} aria-hidden />
          {c.back}
        </button>
      ) : null}
      <button
        type="button"
        className="btn ghost"
        onClick={onCancel}
        data-testid="wizard-cancel"
      >
        {c.cancel}
      </button>
      {dirty ? (
        <span className="hint">
          <span className="dirty-dot" aria-hidden />
          {c.unsavedHint} <Kbd>⌘S</Kbd> {c.saveAnywhere}
        </span>
      ) : step < 4 ? (
        <span className="hint">
          <Kbd>⌘↵</Kbd> {c.nextHint}
        </span>
      ) : null}
    </>
  );
}

export function NextButton({
  label,
  onClick,
  quiet,
}: {
  label: string;
  onClick: () => void;
  quiet?: boolean;
}) {
  const c = useStudioCopy();
  return (
    <button
      type="button"
      className={cx("btn", !quiet && "solid")}
      onClick={onClick}
      data-testid="wizard-next"
    >
      {c.next(label)}
      <ChevronRightIcon size={16} aria-hidden />
    </button>
  );
}

export function SaveButton({
  label,
  onClick,
  dirty,
  primary,
  saving,
}: {
  label: string;
  onClick: () => void;
  dirty: boolean;
  primary?: boolean;
  saving?: boolean;
}) {
  const c = useStudioCopy();
  return (
    <button
      type="button"
      className={cx("btn", primary ? "solid" : dirty && "emph")}
      onClick={() => (dirty || primary ? onClick() : undefined)}
      aria-disabled={!dirty && !primary ? true : undefined}
      title={!dirty && !primary ? c.nothingToSave : undefined}
      disabled={saving}
      data-testid="wizard-save"
    >
      {primary ? <CheckIcon size={16} aria-hidden /> : null}
      {saving ? c.saving : label}
    </button>
  );
}

/**
 * ⌘S saves and ⌘↵ goes to the next step from anywhere in the open Studio,
 * even when focus fell back to the page (an inner editor just closed).
 */
export function useWizardShortcuts(onSave: () => void, onNext: () => void) {
  const latest = useRef({ onSave, onNext });
  latest.current = { onSave, onNext };
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (!(e.metaKey || e.ctrlKey) || e.defaultPrevented) return;
      const target = e.target as HTMLElement | null;
      const inside =
        !target ||
        target === document.body ||
        !!target.closest?.(".oh-studio") ||
        // Focus fell back to the sheet itself (an inner editor closed).
        !!target.querySelector?.(".oh-studio");
      if (!inside) return;
      if (e.key.toLowerCase() === "s") {
        e.preventDefault();
        latest.current.onSave();
      } else if (e.key === "Enter") {
        e.preventDefault();
        latest.current.onNext();
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, []);
}
