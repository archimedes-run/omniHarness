"use client";

import {
  AlertTriangleIcon,
  ArrowRightIcon,
  CheckIcon,
  Loader2Icon,
  MonitorIcon,
  RefreshCwIcon,
  SmartphoneIcon,
  SparkleIcon,
  TabletIcon,
} from "lucide-react";
import {
  forwardRef,
  useEffect,
  useId,
  useRef,
  useState,
  type ReactElement,
  type HTMLAttributes,
} from "react";

import { useOptionalPromptInputController } from "@/components/ai-elements/prompt-input";
import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import type { CheckInfo } from "@/core/artifacts/store-api";
import {
  checkChip,
  checkWords,
  sourceChip,
} from "@/core/artifacts/store-logic";
import { safeField } from "@/core/display/safe";
import { cn } from "@/lib/utils";

/**
 * The artifact viewer's shared parts (one header, chip row and ask box for
 * the chat side panel, the phone overlay and the full page): icon buttons
 * with a tooltip on hover AND keyboard focus (never on touch), the checks
 * and source chips, the preview size toggles and the docked ask box.
 */

export function ViewerHeader({
  className,
  ...props
}: HTMLAttributes<HTMLElement>) {
  return (
    <header
      className={cn(
        "border-border flex min-h-[60px] min-w-0 shrink-0 items-center gap-1.5 border-b pr-3.5 pl-5 max-sm:pr-2 max-sm:pl-3",
        className,
      )}
      {...props}
    />
  );
}

/** 34 px icon buttons (44 px on a touch screen), a visible focus ring. */
export function iconButtonClass(
  opts: { pressed?: boolean; primary?: boolean } = {},
) {
  return cn(
    "inline-flex size-[34px] shrink-0 cursor-pointer items-center justify-center rounded-[9px] border border-transparent transition-colors pointer-coarse:size-11 [&_svg]:size-4 [&_svg]:shrink-0",
    "focus-visible:outline-primary focus-visible:outline-2 focus-visible:outline-offset-2",
    "disabled:pointer-events-none disabled:opacity-50",
    opts.primary
      ? "bg-primary text-primary-foreground hover:brightness-110"
      : opts.pressed
        ? "bg-surface-raised text-foreground border-border"
        : "text-muted-foreground hover:bg-surface-raised hover:text-foreground hover:border-border data-[state=open]:bg-surface-raised data-[state=open]:text-foreground data-[state=open]:border-border",
  );
}

/** Escape presses a tooltip used to hide itself: they still close the
 * phone overlay (a menu, popover or sheet consumes its own Escape). */
export const tooltipEscapes = new WeakSet<Event>();

/** The app's Tooltip around one trigger: its label on hover and on keyboard
 * focus. Radix opens it neither on a touch nor on the focus a tap gives.
 * Keyboard focus is held here as well: tabbing quickly along the toolbar
 * otherwise lost every other tooltip (one closing as the next opened). */
export function Tip({
  label,
  children,
}: {
  label: string;
  children: ReactElement;
}) {
  const [radixOpen, setRadixOpen] = useState(false);
  const [keyboard, setKeyboard] = useState(false);
  return (
    <Tooltip open={radixOpen || keyboard} onOpenChange={setRadixOpen}>
      <TooltipTrigger
        asChild
        onFocus={(e) => {
          if (e.currentTarget.matches(":focus-visible")) setKeyboard(true);
        }}
        onBlur={() => setKeyboard(false)}
        onKeyDown={(e) => {
          if (e.key === "Escape") setKeyboard(false);
        }}
        onPointerDown={() => setKeyboard(false)}
      >
        {children}
      </TooltipTrigger>
      <TooltipContent
        side="bottom"
        sideOffset={8}
        className="rounded-[7px] px-[9px] py-[7px] text-xs leading-none font-medium whitespace-nowrap"
        data-testid="viewer-tooltip"
        onEscapeKeyDown={(e) => {
          tooltipEscapes.add(e);
          setKeyboard(false);
        }}
      >
        {label}
      </TooltipContent>
    </Tooltip>
  );
}

type IconButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> & {
  label: string;
  /** Tooltip text when it says more than the name. */
  tip?: string;
  pressed?: boolean;
  primary?: boolean;
};

/** An icon-only button: its name is `label` (aria-label), shown as its
 * tooltip. `pressed` makes it a toggle (aria-pressed). */
export const IconButton = forwardRef<HTMLButtonElement, IconButtonProps>(
  function IconButton(
    { label, tip, pressed, primary, className, children, ...props },
    ref,
  ) {
    return (
      <Tip label={tip ?? label}>
        <button
          ref={ref}
          type="button"
          aria-label={label}
          aria-pressed={pressed}
          className={cn(iconButtonClass({ pressed, primary }), className)}
          {...props}
        >
          {children}
        </button>
      </Tip>
    );
  },
);

const CHIP =
  "inline-flex h-[26px] max-w-full min-w-0 items-center gap-1.5 rounded-full border px-2.5 text-xs pointer-coarse:h-11";

/** The checks chip (code kinds): short words; a popover with the full
 * sentence, the failures and findings, and "Check again". A real button
 * with aria-expanded; Escape or a click outside closes it and focus
 * returns to the chip. */
export function CheckChip({
  check,
  findings,
  onCheckAgain,
  pending,
}: {
  check: CheckInfo | null | undefined;
  findings: string[];
  onCheckAgain?: () => void;
  pending?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const box = useRef<HTMLDivElement>(null);
  const id = useId();
  const chip = checkChip(check?.state);
  const words = checkWords(check?.state, check?.summary);
  const failures = check?.failures ?? [];

  useEffect(() => {
    if (!open) return;
    // Focus moves into the popover; Escape brings it back to the chip.
    box.current?.focus();
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape") return;
      e.preventDefault();
      e.stopPropagation();
      setOpen(false);
      button.current?.focus();
    };
    const onDown = (e: PointerEvent) => {
      const t = e.target as Node;
      if (!box.current?.contains(t) && !button.current?.contains(t)) {
        setOpen(false);
      }
    };
    document.addEventListener("keydown", onKey, true);
    document.addEventListener("pointerdown", onDown);
    return () => {
      document.removeEventListener("keydown", onKey, true);
      document.removeEventListener("pointerdown", onDown);
    };
  }, [open]);

  const Icon =
    chip.tone === "ok"
      ? CheckIcon
      : chip.tone === "warn"
        ? AlertTriangleIcon
        : check?.state === "pending"
          ? Loader2Icon
          : null;
  return (
    <div className="relative min-w-0">
      <button
        ref={button}
        type="button"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((o) => !o)}
        data-testid="artifact-check"
        data-state={check?.state ?? "none"}
        data-tone={chip.tone}
        className={cn(
          CHIP,
          "focus-visible:outline-primary cursor-pointer focus-visible:outline-2 focus-visible:outline-offset-2",
          chip.tone === "ok" && "border-success/50 text-success",
          chip.tone === "warn" && "border-warning/60 text-warning",
          chip.tone === "neutral" && "border-border text-muted-foreground",
        )}
      >
        {Icon && (
          <Icon
            className={cn(
              "size-3 shrink-0",
              check?.state === "pending" && "animate-spin",
            )}
            strokeWidth={2.5}
            aria-hidden
          />
        )}
        <span className="truncate">{chip.label}</span>
        <span className="sr-only">. Details</span>
      </button>
      {open && (
        <div
          ref={box}
          id={id}
          role="dialog"
          aria-label="Check details"
          tabIndex={-1}
          className="bg-popover text-popover-foreground border-border absolute top-[calc(100%+6px)] left-0 z-40 flex w-[min(320px,calc(100vw-32px))] flex-col gap-2 rounded-xl border p-3 text-xs shadow-lg outline-none"
          data-testid="artifact-check-popover"
        >
          <p className="text-sm" data-testid="artifact-check-sentence">
            {words.label}
          </p>
          {(failures.length > 0 || findings.length > 0) && (
            <ul
              className="text-muted-foreground list-disc pl-4"
              data-testid="artifact-check-details"
            >
              {failures.map((f, i) => (
                <li key={`f${i}`}>{safeField(f)}</li>
              ))}
              {findings.map((f, i) => (
                <li key={`s${i}`}>{safeField(f)}</li>
              ))}
            </ul>
          )}
          {check?.state === "not_checked" && onCheckAgain && (
            <button
              type="button"
              onClick={onCheckAgain}
              disabled={pending}
              className="text-primary inline-flex w-fit items-center gap-1 underline-offset-2 hover:underline disabled:opacity-50 pointer-coarse:min-h-11"
              data-testid="artifact-check-again"
            >
              <RefreshCwIcon className="size-3.5" aria-hidden />
              Check again
            </button>
          )}
        </div>
      )}
    </div>
  );
}

/** The source chip: neutral, except content-originated code that can run. */
export function SourceChip({
  kind,
  lineage,
  source,
}: {
  kind: Parameters<typeof sourceChip>[0];
  lineage: string;
  source: string | null | undefined;
}) {
  const chip = sourceChip(kind, lineage, source);
  return (
    <span
      className={cn(
        CHIP,
        chip.tone === "warn"
          ? "border-warning/60 text-warning"
          : "border-border text-muted-foreground",
      )}
      data-testid="artifact-lineage"
      data-tone={chip.tone}
      title={chip.label}
    >
      {chip.tone === "warn" && (
        <AlertTriangleIcon className="size-3 shrink-0" aria-hidden />
      )}
      <span className="truncate">{chip.label}</span>
    </span>
  );
}

/** A plain neutral chip (e.g. "From a chat you deleted"). */
export function PlainChip({
  children,
  testId,
}: {
  children: React.ReactNode;
  testId?: string;
}) {
  return (
    <span
      className={cn(CHIP, "border-border text-muted-foreground")}
      data-testid={testId}
    >
      <span className="truncate">{children}</span>
    </span>
  );
}

export type Device = "desk" | "tab" | "phone";
export const DEVICE_WIDTH: Record<Device, string> = {
  desk: "100%",
  tab: "760px",
  phone: "380px",
};
const DEVICES: { id: Device; label: string; Icon: typeof MonitorIcon }[] = [
  { id: "desk", label: "Desktop", Icon: MonitorIcon },
  { id: "tab", label: "Tablet", Icon: TabletIcon },
  { id: "phone", label: "Phone", Icon: SmartphoneIcon },
];

/** Preview size: the frame's width (desktop 100%, tablet 760, phone 380). */
export function DeviceToggles({
  device,
  onChange,
}: {
  device: Device;
  onChange: (d: Device) => void;
}) {
  return (
    <div
      role="group"
      aria-label="Preview size"
      className="flex shrink-0 gap-0.5"
      data-testid="artifact-devices"
    >
      {DEVICES.map(({ id, label, Icon }) => (
        <IconButton
          key={id}
          label={label}
          pressed={device === id}
          onClick={() => onChange(id)}
          data-testid={`artifact-device-${id}`}
          className="[&_svg]:size-[15px]"
        >
          <Icon />
        </IconButton>
      ))}
    </div>
  );
}

/** The reference "Ask the assistant to change this" has always put in the
 * composer: the artifact's id and version, never its content. */
export function askRef(artifactId: string, version: number) {
  return `[artifact ${artifactId} v${version}] `;
}

/** True where asking for a change works: inside a chat (its composer). */
export function useCanAsk() {
  return useOptionalPromptInputController() !== null;
}

/**
 * The docked "Ask for a change…" box (only in a chat). It sends what the old
 * "Ask the assistant to change this" button led to: the reference, then the
 * owner's words, as this chat's next message. A draft already in the chat
 * box is kept: the request is put in front of it and the chat box focused,
 * for the owner to send.
 */
export const AskBox = forwardRef<
  HTMLInputElement,
  { artifactId: string; version: number }
>(function AskBox({ artifactId, version }, ref) {
  const controller = useOptionalPromptInputController();
  const [text, setText] = useState("");
  const [sending, setSending] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);
  const composerValue = controller?.textInput.value;

  // Submit once the composer holds the request (the form reads it on submit).
  useEffect(() => {
    if (sending === null || composerValue !== sending) return;
    const id = requestAnimationFrame(() => {
      setSending(null);
      const box = document.querySelector<HTMLTextAreaElement>(
        "textarea[name='message']",
      );
      const submit = box?.form?.querySelector<HTMLButtonElement>(
        'button[type="submit"]',
      );
      if (box?.form && submit && !submit.disabled) {
        box.form.requestSubmit();
      } else {
        setNote("Your request is in the chat box: send it from there.");
        box?.focus();
      }
    });
    return () => cancelAnimationFrame(id);
  }, [sending, composerValue]);

  if (!controller) return null;
  const words = text.trim();
  const send = () => {
    if (!words) return;
    setNote(null);
    const request = `${askRef(artifactId, version)}${words}`;
    const draft = controller.textInput.value;
    setText("");
    if (draft.trim()) {
      controller.textInput.setInput(`${request}\n\n${draft}`);
      setNote("Added in front of your draft in the chat box: send it there.");
      requestAnimationFrame(() =>
        document
          .querySelector<HTMLTextAreaElement>("textarea[name='message']")
          ?.focus(),
      );
      return;
    }
    controller.textInput.setInput(request);
    setSending(request);
  };
  return (
    <div
      className="border-border shrink-0 border-t px-5 pt-3 pb-4 max-sm:px-3"
      data-testid="artifact-ask-box"
    >
      <form
        className="bg-card border-border focus-within:border-primary flex items-center gap-2.5 rounded-[14px] border py-2 pr-2 pl-3.5"
        onSubmit={(e) => {
          e.preventDefault();
          send();
        }}
      >
        <SparkleIcon className="text-primary size-4 shrink-0" aria-hidden />
        <label className="min-w-0 flex-1">
          <span className="sr-only">Ask for a change</span>
          <input
            ref={ref}
            type="text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder="Ask for a change… e.g. “make the buttons larger”"
            className="placeholder:text-muted-foreground w-full min-w-0 bg-transparent text-sm outline-none pointer-coarse:min-h-11"
            data-testid="artifact-ask-input"
          />
        </label>
        <button
          type="submit"
          aria-label="Send change request"
          disabled={!words}
          className={cn(
            iconButtonClass({ primary: true }),
            "rounded-[10px] [&_svg]:size-[15px]",
          )}
          data-testid="artifact-ask-send"
        >
          <ArrowRightIcon strokeWidth={2.4} />
        </button>
      </form>
      {note && (
        <p
          role="status"
          className="text-muted-foreground mt-1.5 text-xs"
          data-testid="artifact-ask-note"
        >
          {note}
        </p>
      )}
    </div>
  );
});
