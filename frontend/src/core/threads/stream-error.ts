/**
 * What the chat says when its reply stream fails, or null to say nothing.
 *
 * A raw HTTP error body never reaches a toast. After a gateway restart the
 * chat reconnects to its last run, which this gateway no longer streams:
 * "HTTP 404: {"detail":"Run … not found"}" appeared as a red toast on every
 * reload, although the chat already shows the run's outcome (an
 * interrupted run carries its own notice). A run that is gone is quiet.
 */
const RUN_GONE = /\brun\b[^"]*\bnot found\b/i;
const HTTP_BODY = /^\s*HTTP\s+(\d{3})\b/i;

export const STREAM_FAILED =
  "The reply could not be reached. Reload the chat to see the latest.";

function rawMessage(error: unknown): string {
  if (typeof error === "string") return error;
  if (error instanceof Error) return error.message;
  if (typeof error === "object" && error !== null) {
    const message = Reflect.get(error, "message");
    if (typeof message === "string") return message;
    const nested = Reflect.get(error, "error");
    if (nested instanceof Error) return nested.message;
    if (typeof nested === "string") return nested;
  }
  return "";
}

export function streamErrorToast(error: unknown): string | null {
  const message = rawMessage(error).trim();
  const http = HTTP_BODY.exec(message);
  if (http) {
    // The run is no longer live here (it ended, or a restart ended it).
    if (http[1] === "404" && RUN_GONE.test(message)) return null;
    return STREAM_FAILED;
  }
  if (!message) return "Request failed.";
  // Any other message that carries a JSON body is not shown as is.
  if (/[{[]\s*"/.test(message)) return STREAM_FAILED;
  return message;
}
