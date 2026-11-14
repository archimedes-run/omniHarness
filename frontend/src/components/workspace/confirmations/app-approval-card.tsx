"use client";

import { useQueryClient } from "@tanstack/react-query";
import { CheckIcon, LayoutGridIcon, Loader2Icon } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Button } from "@/components/ui/button";
import { AppsApiError, type ApprovalCard } from "@/core/apps/api";
import { useApproveApp, useKeepAppVersion } from "@/core/apps/hooks";
import { hashGroups, writeError } from "@/core/apps/wording";
import { cn } from "@/lib/utils";

import { COMPOSER_INSET_VAR } from "../chats/use-composer-inset";

/**
 * Spec 011 FR-006, FR-007: the App access card. Each source in the gateway's
 * own words (built from the catalog entry, its fields and params, never from
 * text the app or the worker wrote; the app's name is a title only), how often
 * it refreshes, the sentence that the assistant never sees the data, and the
 * manifest hash the press approves.
 *
 * BUTTON ONLY (010 FR-016): Allow is the one way to grant. Nothing is
 * pre-ticked, there is nothing to tick, and typed chat text never grants. The
 * press posts the hash this card showed; if the app changed since, the
 * gateway refuses (409) and the card is reloaded.
 */
export function AppApprovalCard({
  card,
  heading = "App access",
  className,
  reveal = false,
}: {
  card: ApprovalCard;
  heading?: string;
  className?: string;
  /** In a chat: scroll a pending card fully into view, above the composer. */
  reveal?: boolean;
}) {
  const ref = useRef<HTMLElement>(null);
  const approve = useApproveApp();
  const keep = useKeepAppVersion();
  const client = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const resolved = card.status !== "pending";
  useEffect(() => {
    if (reveal && !resolved) {
      ref.current?.scrollIntoView({ block: "end", behavior: "smooth" });
    }
    // Once per card, when it is raised.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [card.id, reveal]);

  const onAllow = () => {
    setError(null);
    approve.mutate(
      { id: card.app_id, manifestHash: card.manifest_hash, cardId: card.id },
      {
        onError: (err) => {
          const code = err instanceof AppsApiError ? err.code : "error";
          setError(writeError(code, err.message));
          if (code === "hash_mismatch") {
            void client.invalidateQueries({ queryKey: ["apps"] });
            void client.invalidateQueries({ queryKey: ["appApprovals"] });
          }
        },
      },
    );
  };

  const titleId = `app-card-${card.id}`;
  if (card.kind === "version") {
    const keeps = card.keeps_version ?? card.version - 1;
    const onKeep = () => {
      setError(null);
      keep.mutate(
        { id: card.app_id, cardId: card.id },
        { onError: (err) => setError(writeError("error", err.message)) },
      );
    };
    return (
      <section
        ref={ref}
        aria-labelledby={titleId}
        style={{
          scrollMarginBottom: `calc(var(${COMPOSER_INSET_VAR}, 200px) + 24px)`,
        }}
        data-testid="app-approval-card"
        data-kind="version"
        data-card-id={card.id}
        data-status={card.status}
        className={cn(
          "bg-card border-border w-full max-w-[640px] rounded-xl border px-[18px] py-4 text-sm",
          className,
        )}
      >
        <div className="flex items-start gap-3">
          <span
            aria-hidden
            className="bg-primary-subtle text-primary flex size-8 shrink-0 items-center justify-center rounded-lg"
          >
            <LayoutGridIcon className="size-4" />
          </span>
          <div className="min-w-0 flex-1">
            <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
              New version
            </p>
            <h3 id={titleId} className="text-[15px] font-semibold break-words">
              {`${card.app_name}: use version ${card.version}?`}
            </h3>
          </div>
        </div>
        {card.suggestion && (
          <p
            className="border-warning/40 bg-warning/10 text-foreground mt-3 rounded-md border px-3 py-2 text-xs"
            data-testid="app-card-suggestion"
          >
            <strong className="font-semibold">Suggestion.</strong>{" "}
            {card.suggestion_words ? `${card.suggestion_words} ` : ""}
            It was not your own request.
          </p>
        )}
        {card.description ? (
          <div className="mt-3" data-testid="app-card-description">
            <p className="text-muted-foreground text-xs">
              The assistant&apos;s description of the change:
            </p>
            <blockquote className="border-border mt-1 border-l-2 pl-3 break-words">
              {card.description}
            </blockquote>
          </div>
        ) : null}
        <p className="mt-3" data-testid="app-card-checks">
          {card.checks_passed
            ? "It passed the system's checks. It reads the same data as the version you use now."
            : "It reads the same data as the version you use now."}
        </p>
        <p className="text-muted-foreground mt-1 text-xs">
          {`Version ${keeps} keeps running until you choose.`}
        </p>
        <div className="mt-4 flex flex-wrap items-center gap-3">
          {card.status === "pending" ? (
            <>
              <Button
                type="button"
                onClick={onAllow}
                disabled={
                  approve.isPending || approve.isSuccess || keep.isPending
                }
                data-testid="app-card-use-version"
                className="max-md:min-h-11"
              >
                {approve.isPending && <Loader2Icon className="animate-spin" />}
                {approve.isSuccess
                  ? `Using version ${card.version}`
                  : `Use version ${card.version}`}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={onKeep}
                disabled={approve.isPending || keep.isPending || keep.isSuccess}
                data-testid="app-card-keep-version"
                className="max-md:min-h-11"
              >
                {keep.isSuccess
                  ? `Kept version ${keeps}`
                  : `Keep version ${keeps}`}
              </Button>
            </>
          ) : (
            <p
              className="text-muted-foreground inline-flex items-center gap-1.5"
              data-testid="app-card-resolved"
            >
              {card.status === "approved" ? (
                <>
                  <CheckIcon className="text-success size-4" aria-hidden />
                  {`Using version ${card.version}`}
                </>
              ) : card.status === "kept" ? (
                `Kept version ${keeps}`
              ) : (
                "Replaced by a newer version of this app"
              )}
            </p>
          )}
          {!resolved && (
            <p className="text-muted-foreground text-xs">
              Only these buttons decide. Typing in chat does not.
            </p>
          )}
        </div>
        {error && (
          <p className="text-destructive mt-2 text-xs" role="alert">
            {error}
          </p>
        )}
      </section>
    );
  }
  return (
    <section
      ref={ref}
      aria-labelledby={titleId}
      // The composer floats over the bottom of the thread: stop above it.
      style={{
        scrollMarginBottom: `calc(var(${COMPOSER_INSET_VAR}, 200px) + 24px)`,
      }}
      data-testid="app-approval-card"
      data-card-id={card.id}
      data-status={card.status}
      className={cn(
        "bg-card border-border w-full max-w-[640px] rounded-xl border px-[18px] py-4 text-sm",
        className,
      )}
    >
      <div className="flex items-start gap-3">
        <span
          aria-hidden
          className="bg-primary-subtle text-primary flex size-8 shrink-0 items-center justify-center rounded-lg"
        >
          <LayoutGridIcon className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
            {heading}
          </p>
          <h3 id={titleId} className="text-[15px] font-semibold break-words">
            {card.app_name}{" "}
            <span className="text-muted-foreground font-normal">
              version {card.version}
            </span>
          </h3>
        </div>
      </div>

      {card.suggestion && (
        <p
          className="border-warning/40 bg-warning/10 text-foreground mt-3 rounded-md border px-3 py-2 text-xs"
          data-testid="app-card-suggestion"
        >
          <strong className="font-semibold">Suggestion.</strong>{" "}
          {/* The gateway's own line, rendered as text; never the raw source. */}
          {card.suggestion_words ? `${card.suggestion_words} ` : ""}
          It was not your own request. Allow it only if you want this app.
        </p>
      )}

      <p className="mt-3">This app wants to:</p>
      <ul className="mt-2 flex flex-col gap-2" data-testid="app-card-sources">
        {card.sources.map((s) => (
          <li
            key={s.name}
            className="border-border rounded-md border px-3 py-2"
            data-source={s.name}
          >
            <p className="break-words">{s.words}</p>
            <p className="text-muted-foreground mt-0.5 text-xs">
              {s.refresh_words}
            </p>
          </li>
        ))}
      </ul>
      <p className="mt-3 font-medium" data-testid="app-card-sentence">
        {card.sentence}
      </p>
      <p className="text-muted-foreground mt-2 text-xs">
        Allowing approves exactly this list (manifest{" "}
        <code
          className="text-foreground font-mono text-[12px] break-words"
          data-testid="app-card-hash"
          title={card.manifest_hash}
        >
          {hashGroups(card.manifest_hash)}
        </code>
        ). If a later version asks for anything different, you will be asked
        again.
      </p>

      <div className="mt-4 flex flex-wrap items-center gap-3">
        {card.status === "pending" ? (
          <Button
            type="button"
            onClick={onAllow}
            disabled={approve.isPending || approve.isSuccess}
            data-testid="app-card-allow"
            className="max-md:min-h-11"
          >
            {approve.isPending && <Loader2Icon className="animate-spin" />}
            {approve.isSuccess ? "Allowed" : "Allow"}
          </Button>
        ) : (
          <p
            className="text-muted-foreground inline-flex items-center gap-1.5"
            data-testid="app-card-resolved"
          >
            {card.status === "approved" ? (
              <>
                <CheckIcon className="text-success size-4" aria-hidden />
                Allowed
              </>
            ) : (
              "Replaced by a newer version of this app"
            )}
          </p>
        )}
        {!resolved && (
          <p className="text-muted-foreground text-xs">
            Only this button allows it. Typing in chat does not.
          </p>
        )}
      </div>
      {error && (
        <p className="text-destructive mt-2 text-xs" role="alert">
          {error}
        </p>
      )}
    </section>
  );
}
