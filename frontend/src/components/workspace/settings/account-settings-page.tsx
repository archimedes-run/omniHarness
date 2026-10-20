"use client";

import { LogOutIcon } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { fetch, getCsrfHeaders } from "@/core/api/fetcher";
import { useAuth } from "@/core/auth/AuthProvider";
import { parseAuthError } from "@/core/auth/types";
import { useI18n } from "@/core/i18n/hooks";
import { usePreferences, useSaveDisplayName } from "@/core/preferences";

import { SettingsSection } from "./settings-section";

export function AccountSettingsPage() {
  const { user, logout } = useAuth();
  const { t } = useI18n();
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setMessage("");

    if (newPassword !== confirmPassword) {
      setError(t.settings.account.passwordMismatch);
      return;
    }
    if (newPassword.length < 8) {
      setError(t.settings.account.passwordTooShort);
      return;
    }

    setLoading(true);
    try {
      const res = await fetch("/api/v1/auth/change-password", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getCsrfHeaders(),
        },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });

      if (!res.ok) {
        const data = await res.json();
        const authError = parseAuthError(data);
        setError(authError.message);
        return;
      }

      setMessage(t.settings.account.passwordChangedSuccess);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch {
      setError(t.settings.account.networkError);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-5">
      <SettingsSection title={t.settings.account.profileTitle}>
        <div className="space-y-2">
          <div className="grid grid-cols-[max-content_max-content] items-center gap-4">
            <span className="text-muted-foreground text-sm">
              {t.settings.account.email}
            </span>
            <span className="text-sm font-medium">{user?.email ?? "—"}</span>
            <span className="text-muted-foreground text-sm">
              {t.settings.account.role}
            </span>
            <span className="text-sm font-medium capitalize">
              {user?.system_role ?? "—"}
            </span>
          </div>
        </div>
        <DisplayNameField email={user?.email} />
      </SettingsSection>

      <SettingsSection
        title={t.settings.account.changePasswordTitle}
        description={t.settings.account.changePasswordDescription}
      >
        <form onSubmit={handleChangePassword} className="max-w-sm space-y-3">
          <Input
            type="password"
            placeholder={t.settings.account.currentPassword}
            value={currentPassword}
            onChange={(e) => setCurrentPassword(e.target.value)}
            required
          />
          <Input
            type="password"
            placeholder={t.settings.account.newPassword}
            value={newPassword}
            onChange={(e) => setNewPassword(e.target.value)}
            required
            minLength={8}
          />
          <Input
            type="password"
            placeholder={t.settings.account.confirmNewPassword}
            value={confirmPassword}
            onChange={(e) => setConfirmPassword(e.target.value)}
            required
            minLength={8}
          />
          {error && <p className="text-destructive text-sm">{error}</p>}
          {message && <p className="text-success text-sm">{message}</p>}
          <Button type="submit" variant="outline" size="sm" disabled={loading}>
            {loading
              ? t.settings.account.updating
              : t.settings.account.updatePassword}
          </Button>
        </form>
      </SettingsSection>

      <SettingsSection title="" description="">
        <Button
          variant="destructive"
          size="sm"
          onClick={logout}
          className="gap-2"
        >
          <LogOutIcon className="size-4" />
          {t.settings.account.signOut}
        </Button>
      </SettingsSection>
    </div>
  );
}

/** Optional display name, stored per user on the server. */
function DisplayNameField({ email }: { email?: string }) {
  const { t } = useI18n();
  const { preferences, error } = usePreferences();
  const save = useSaveDisplayName();
  const [value, setValue] = useState("");
  useEffect(() => {
    if (preferences) setValue(preferences.display_name ?? "");
  }, [preferences]);
  const fallback = email?.split("@")[0] ?? "";

  return (
    <form
      className="mt-6 max-w-sm space-y-2"
      onSubmit={(e) => {
        e.preventDefault();
        save.mutate(value.trim() || null);
      }}
    >
      <label
        htmlFor="display-name"
        className="text-muted-foreground block text-sm"
      >
        {t.settings.account.displayName}
      </label>
      <div className="flex gap-2">
        <Input
          id="display-name"
          data-testid="display-name"
          value={value}
          maxLength={64}
          placeholder={fallback}
          disabled={!preferences}
          onChange={(e) => setValue(e.target.value)}
        />
        <Button
          type="submit"
          variant="outline"
          size="sm"
          disabled={!preferences || save.isPending}
          className="min-h-9"
        >
          {t.settings.account.displayNameSave}
        </Button>
      </div>
      <p
        role="status"
        data-testid="display-name-status"
        className={
          save.isError || error
            ? "text-destructive text-xs"
            : "text-muted-foreground text-xs"
        }
      >
        {error && !preferences
          ? t.settings.account.displayNameUnknown
          : save.isError
            ? t.settings.account.displayNameFailed
            : save.isSuccess
              ? t.settings.account.displayNameSaved
              : t.settings.account.displayNameHint.replace(
                  "{fallback}",
                  fallback,
                )}
      </p>
    </form>
  );
}
