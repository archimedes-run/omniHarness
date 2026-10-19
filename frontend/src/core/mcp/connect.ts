import { getComposioConnectionStatus, initiateComposioConnection } from "./api";

export type ConnectOutcome = "connected" | "already-connected" | "timed-out";

/**
 * Connect a Composio toolkit: start OAuth in a popup, then wait until the
 * connection is live. One implementation, used by Settings → Connections and
 * by the MCP server catalog beneath it.
 *
 * connect.composio.dev sends Cross-Origin-Opener-Policy headers that sever the
 * opener-popup link, so `popup.closed` cannot be read. Completion is learned
 * from the callback page's postMessage, or by polling our own API, which syncs
 * from Composio while a connection is pending (up to 80 s).
 */
export async function connectComposioToolkit(
  toolkit: string,
  onPending?: () => void,
): Promise<ConnectOutcome> {
  const callbackUrl = `${window.location.origin}/workspace/mcp/callback?toolkit=${toolkit}`;
  const result = await initiateComposioConnection(toolkit, callbackUrl);
  if ("status" in result && result.status === "already_connected") {
    return "already-connected";
  }
  onPending?.();
  const popup = window.open(
    (result as { composio_redirect_url: string }).composio_redirect_url,
    "composio_oauth",
    "width=600,height=700",
  );

  return new Promise<ConnectOutcome>((resolve) => {
    let attempts = 0;
    const finish = (outcome: ConnectOutcome) => {
      clearInterval(timer);
      window.removeEventListener("message", onMessage);
      if (outcome === "connected") popup?.close();
      resolve(outcome);
    };
    const onMessage = (ev: MessageEvent) => {
      const data = ev.data as { type?: string; toolkit?: string } | null;
      if (data?.type === "composio_connected" && data.toolkit === toolkit) {
        finish("connected");
      }
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
        } catch {
          /* retry on transient error */
        }
        if (attempts >= 40) finish("timed-out");
      })();
    }, 2000);
    window.addEventListener("message", onMessage);
  });
}
