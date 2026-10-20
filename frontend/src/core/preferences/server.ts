import { cookies } from "next/headers";

import { getGatewayConfig } from "@/core/auth/gateway-config";

import {
  parseAppearancePreference,
  type AppearancePreference,
} from "./appearance";

const TIMEOUT_MS = 1_500;

/**
 * The signed-in user's stored appearance, read during SSR so it can be
 * applied before first paint. Null means "could not tell" (no session, the
 * gateway did not answer): the client then asks once it has loaded.
 */
export async function getServerSideAppearance(): Promise<AppearancePreference | null> {
  const session = (await cookies()).get("access_token");
  if (!session) return null;
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), TIMEOUT_MS);
  try {
    const { internalGatewayUrl } = getGatewayConfig();
    const res = await fetch(
      `${internalGatewayUrl}/api/preferences/appearance`,
      {
        headers: { Cookie: `access_token=${session.value}` },
        cache: "no-store",
        signal: controller.signal,
      },
    );
    return res.ok ? parseAppearancePreference(await res.json()) : null;
  } catch {
    return null;
  } finally {
    clearTimeout(timeout);
  }
}
