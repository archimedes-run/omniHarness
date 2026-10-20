"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { useDismissNamePrompt, useHomeDismissals } from "@/core/home/hooks";
import { usePreferences, useSaveDisplayName } from "@/core/preferences";

/**
 * Asked once, on the first Home visit: what to call you. Saving uses the
 * display-name endpoint; "Not now" is kept on the server, so it is not asked
 * again on any device. Shown only when both facts are known: no name is set,
 * and the prompt was never answered.
 */
export function NamePrompt() {
  const { preferences } = usePreferences();
  const { dismissals } = useHomeDismissals();
  const save = useSaveDisplayName();
  const notNow = useDismissNamePrompt();
  const [name, setName] = useState("");
  const submit = () => {
    if (name.trim()) save.mutate(name.trim());
  };

  if (!preferences || !dismissals) return null;
  if (preferences.display_name != null || dismissals.name_prompt_dismissed)
    return null;

  return (
    <form
      className="bg-card border-border flex flex-wrap items-center gap-3 rounded-xl border px-5 py-3.5"
      data-testid="name-prompt"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <label
        htmlFor="home-display-name"
        className="text-foreground text-sm font-medium"
      >
        What should I call you?
      </label>
      <Input
        id="home-display-name"
        className="h-9 w-56 max-md:h-11"
        value={name}
        maxLength={64}
        onChange={(event) => setName(event.target.value)}
        placeholder={preferences.display_name_effective}
        autoComplete="nickname"
      />
      <Button
        // Not type="submit": that styles it as the page's primary button.
        type="button"
        variant="outline"
        onClick={submit}
        className="max-md:min-h-11"
        disabled={!name.trim() || save.isPending}
      >
        Save
      </Button>
      <Button
        type="button"
        variant="ghost"
        className="max-md:min-h-11"
        disabled={notNow.isPending}
        onClick={() => notNow.mutate()}
        data-testid="name-prompt-not-now"
      >
        Not now
      </Button>
      {(save.isError || notNow.isError) && (
        <p className="text-destructive w-full text-sm" role="alert">
          {`That was not saved: ${(save.error ?? notNow.error)?.message ?? ""}`}
        </p>
      )}
    </form>
  );
}
