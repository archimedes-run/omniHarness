"use client";

import { MonitorSmartphoneIcon, MoonIcon, SunIcon } from "lucide-react";
import { useTheme } from "next-themes";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type ComponentType,
  type KeyboardEvent,
  type SVGProps,
} from "react";

import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Separator } from "@/components/ui/separator";
import { enUS, isLocale, zhCN, type Locale } from "@/core/i18n";
import { useI18n } from "@/core/i18n/hooks";
import {
  isAppearance,
  saveAppearance,
  type Appearance,
} from "@/core/preferences";
import { cn } from "@/lib/utils";

import { SettingsSection } from "./settings-section";

const languageOptions: { value: Locale; label: string }[] = [
  { value: "en-US", label: enUS.locale.localName },
  { value: "zh-CN", label: zhCN.locale.localName },
];

type SaveState = "idle" | "saving" | "saved" | "failed";

export function AppearanceSettingsPage() {
  const { t, locale, changeLocale } = useI18n();
  const { theme, setTheme } = useTheme();
  // What is selected comes from next-themes' own cache (localStorage), read
  // once mounted, and then follows every change of `theme`. Measured in
  // tests/rendering/theme.spec.ts: on this lazily loaded page, `theme` alone
  // read undefined or "system" while the page was painted light from the
  // cache, so the wrong card was selected.
  const [choice, setChoice] = useState<Appearance | null>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    setReady(true);
    try {
      const cached = localStorage.getItem("theme");
      if (isAppearance(cached)) setChoice(cached);
    } catch {}
  }, []);
  useEffect(() => {
    if (isAppearance(theme)) setChoice(theme);
  }, [theme]);
  const currentTheme: Appearance = choice ?? "system";
  const [save, setSave] = useState<SaveState>("idle");
  const latest = useRef(0);

  const themeOptions = useMemo(
    () =>
      [
        {
          id: "light",
          label: t.settings.appearance.light,
          description: t.settings.appearance.lightDescription,
          icon: SunIcon,
        },
        {
          id: "dark",
          label: t.settings.appearance.dark,
          description: t.settings.appearance.darkDescription,
          icon: MoonIcon,
        },
        {
          id: "system",
          label: t.settings.appearance.system,
          description: t.settings.appearance.systemDescription,
          icon: MonitorSmartphoneIcon,
        },
      ] as const,
    [t],
  );

  // Apply at once, then remember it on the server for this user. A failed
  // save is said in words: this browser still remembers it, the account does not.
  const choose = (value: Appearance) => {
    setChoice(value);
    setTheme(value);
    const call = ++latest.current;
    setSave("saving");
    saveAppearance(value).then(
      () => call === latest.current && setSave("saved"),
      () => call === latest.current && setSave("failed"),
    );
  };

  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKeyDown = (event: KeyboardEvent, index: number) => {
    const step =
      event.key === "ArrowRight" || event.key === "ArrowDown"
        ? 1
        : event.key === "ArrowLeft" || event.key === "ArrowUp"
          ? -1
          : 0;
    if (!step) return;
    event.preventDefault();
    const next = (index + step + themeOptions.length) % themeOptions.length;
    refs.current[next]?.focus();
    choose(themeOptions[next]!.id);
  };

  return (
    <div className="space-y-8">
      <SettingsSection
        title={t.settings.appearance.themeTitle}
        description={t.settings.appearance.themeDescription}
      >
        <div
          role="radiogroup"
          data-ready={ready || undefined}
          aria-label={t.settings.appearance.themeTitle}
          className="grid gap-3 sm:grid-cols-3"
        >
          {themeOptions.map((option, index) => (
            <ThemeOption
              key={option.id}
              ref={(el) => {
                refs.current[index] = el;
              }}
              icon={option.icon}
              label={option.label}
              description={option.description}
              mode={option.id}
              checked={currentTheme === option.id}
              onSelect={choose}
              onKeyDown={(e) => onKeyDown(e, index)}
            />
          ))}
        </div>
        <p
          role="status"
          data-testid="appearance-save-state"
          className={cn(
            "mt-3 min-h-5 text-xs",
            save === "failed" ? "text-warning" : "text-muted-foreground",
          )}
        >
          {save === "saving" && t.settings.appearance.saving}
          {save === "saved" && t.settings.appearance.savedToAccount}
          {save === "failed" && t.settings.appearance.saveFailed}
        </p>
      </SettingsSection>

      <Separator />

      <SettingsSection
        title={t.settings.appearance.languageTitle}
        description={t.settings.appearance.languageDescription}
      >
        <Select
          value={locale}
          onValueChange={(value) => {
            if (isLocale(value)) {
              changeLocale(value);
            }
          }}
        >
          <SelectTrigger className="w-[220px]">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {languageOptions.map((item) => (
              <SelectItem key={item.value} value={item.value}>
                {item.label}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </SettingsSection>
    </div>
  );
}

function ThemeOption({
  ref,
  icon: Icon,
  label,
  description,
  mode,
  checked,
  onSelect,
  onKeyDown,
}: {
  ref: (el: HTMLButtonElement | null) => void;
  icon: ComponentType<SVGProps<SVGSVGElement>>;
  label: string;
  description: string;
  mode: Appearance;
  checked: boolean;
  onSelect: (mode: Appearance) => void;
  onKeyDown: (event: KeyboardEvent) => void;
}) {
  return (
    <button
      ref={ref}
      type="button"
      role="radio"
      aria-checked={checked}
      tabIndex={checked ? 0 : -1}
      data-testid={`theme-option-${mode}`}
      onClick={() => onSelect(mode)}
      onKeyDown={onKeyDown}
      className={cn(
        "bg-card text-card-foreground focus-visible:ring-ring flex min-h-11 flex-col gap-3 rounded-xl border p-3 text-left transition-colors outline-none focus-visible:ring-2",
        checked ? "border-primary" : "hover:border-border-strong",
      )}
    >
      {mode === "system" ? (
        <div className="grid grid-cols-2 overflow-hidden rounded-lg border">
          <Preview theme="light" className="rounded-none border-0" />
          <Preview theme="dark" className="rounded-none border-0" />
        </div>
      ) : (
        <Preview theme={mode} />
      )}
      <div className="flex items-start gap-2">
        <Icon aria-hidden className="text-muted-foreground mt-0.5 size-4" />
        <div className="space-y-0.5">
          <div className="text-sm font-medium">{label}</div>
          <p className="text-muted-foreground text-xs leading-snug">
            {description}
          </p>
        </div>
      </div>
    </button>
  );
}

/**
 * A miniature of the workspace drawn with the real tokens: the `light` or
 * `dark` class on the wrapper scopes every token to that theme, so the
 * preview cannot drift from what the theme actually paints.
 */
function Preview({
  theme,
  className,
}: {
  theme: "light" | "dark";
  className?: string;
}) {
  return (
    <div
      aria-hidden
      className={cn(
        theme,
        "bg-background flex h-20 overflow-hidden rounded-lg border",
        className,
      )}
    >
      <div className="bg-sidebar border-sidebar-border flex w-1/4 flex-col gap-1 border-r p-1.5">
        <div className="bg-primary h-1.5 w-3/4 rounded-full" />
        <div className="bg-sidebar-accent h-1.5 rounded-full" />
        <div className="bg-muted-foreground/40 h-1.5 w-2/3 rounded-full" />
      </div>
      <div className="flex flex-1 flex-col gap-1.5 p-2">
        <div className="bg-foreground/70 h-1.5 w-1/2 rounded-full" />
        <div className="bg-card flex flex-1 flex-col gap-1 rounded-md border p-1.5">
          <div className="bg-foreground-2/50 h-1 w-3/4 rounded-full" />
          <div className="bg-success h-1 w-1/3 rounded-full" />
        </div>
      </div>
    </div>
  );
}
