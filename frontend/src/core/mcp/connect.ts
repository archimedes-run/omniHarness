import { getComposioConnectionStatus, initiateComposioConnection } from "./api";

/**
 * How a connect attempt ended. "blocked": the browser refused to open the
 * sign-in window. "cancelled": the person stopped waiting (the caller's
 * AbortSignal). "failed": Composio or the callback page reported a failure.
 * "timed-out": nothing was heard back in time, which cannot be told apart
 * from the window having been closed (see below).
 */
export type ConnectOutcome =
  | "connected"
  | "already-connected"
  | "timed-out"
  | "blocked"
  | "cancelled"
  | "failed";

/** The callback page tells its opener how sign-in ended. */
export const CONNECTED_MESSAGE = "composio_connected";
export const FAILED_MESSAGE = "composio_failed";

/**
 * Connect a Composio toolkit: start OAuth in a popup, then wait until the
 * connection is live. One implementation, used by Settings → Connections, by
 * the MCP server catalog, and by the chat bar's "+" picker.
 *
 * The window is opened before anything is awaited, while the click still
 * counts as a user gesture, so a popup blocker lets it through; it is then
 * pointed at Composio's sign-in page. A null window means it was blocked.
 *
 * connect.composio.dev sends Cross-Origin-Opener-Policy headers that sever the
 * opener-popup link, so `popup.closed` cannot be read. Completion is learned
 * from the callback page's postMessage, or by polling our own API, which syncs
 * from Composio while a connection is pending (up to 80 s).
 */
export async function connectComposioToolkit(
  toolkit: string,
  onPending?: () => void,
  options: { signal?: AbortSignal } = {},
): Promise<ConnectOutcome> {
  const { signal } = options;
  const popup = window.open("", "composio_oauth", "width=600,height=700");
  if (!popup) return "blocked";

  const callbackUrl = `${window.location.origin}/workspace/mcp/callback?toolkit=${toolkit}`;
  let result: Awaited<ReturnType<typeof initiateComposioConnection>>;
  try {
    result = await initiateComposioConnection(toolkit, callbackUrl);
  } catch (err) {
    popup.close();
    throw err;
  }
  if ("status" in result && result.status === "already_connected") {
    popup.close();
    return "already-connected";
  }
  const started = result as {
    composio_redirect_url?: string;
    detail?: unknown;
  };
  if (!started.composio_redirect_url) {
    popup.close();
    throw new Error(
      typeof started.detail === "string"
        ? started.detail
        : "Composio did not return a sign-in page.",
    );
  }
  if (signal?.aborted) {
    popup.close();
    return "cancelled";
  }
  popup.location.href = started.composio_redirect_url;
  onPending?.();

  return new Promise<ConnectOutcome>((resolve) => {
    let attempts = 0;
    let done = false;
    const finish = (outcome: ConnectOutcome) => {
      if (done) return;
      done = true;
      clearInterval(timer);
      window.removeEventListener("message", onMessage);
      signal?.removeEventListener("abort", onAbort);
      if (outcome !== "timed-out") popup.close();
      resolve(outcome);
    };
    const onAbort = () => finish("cancelled");
    const onMessage = (ev: MessageEvent) => {
      if (ev.origin !== window.location.origin) return;
      const data = ev.data as { type?: string; toolkit?: string } | null;
      if (data?.toolkit !== toolkit) return;
      if (data.type === CONNECTED_MESSAGE) finish("connected");
      else if (data.type === FAILED_MESSAGE) finish("failed");
    };
    const timer = setInterval(() => {
      attempts++;
      void (async () => {
        try {
          const status = await getComposioConnectionStatus(toolkit);
          if (status.status === "active" || status.status === "connected") {
            finish("connected");
            return;
          }
          if (status.status === "failed") {
            finish("failed");
            return;
          }
        } catch {
          /* retry on transient error */
        }
        if (attempts >= 40) finish("timed-out");
      })();
    }, 2000);
    window.addEventListener("message", onMessage);
    signal?.addEventListener("abort", onAbort);
  });
}
