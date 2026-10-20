"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { getComposioConnectionStatus } from "@/core/mcp/api";
import { CONNECTED_MESSAGE, FAILED_MESSAGE } from "@/core/mcp/connect";

/** The window that opened sign-in learns how it ended, in words it reads. */
function tellOpener(type: string, toolkit: string) {
  window.opener?.postMessage({ type, toolkit }, window.location.origin);
}

export default function ComposioCallbackPage() {
  const params = useSearchParams();
  const router = useRouter();
  const toolkit = params.get("toolkit") ?? "";
  const [state, setState] = useState<"polling" | "connected" | "failed">(
    "polling",
  );
  const [account, setAccount] = useState<string | null>(null);

  useEffect(() => {
    if (!toolkit) {
      setState("failed");
      return;
    }
    // Composio sends the person back with status=failed or an error when
    // sign-in was refused or went wrong.
    if (params.get("status") === "failed" || params.get("error")) {
      setState("failed");
      tellOpener(FAILED_MESSAGE, toolkit);
      return;
    }
    let attempts = 0;
    const timer = setInterval(() => {
      attempts++;
      void (async () => {
        try {
          const status = await getComposioConnectionStatus(toolkit);
          if (status.status === "active" || status.status === "connected") {
            setAccount(status.account_display);
            setState("connected");
            clearInterval(timer);
            setTimeout(() => {
              if (window.opener) {
                tellOpener(CONNECTED_MESSAGE, toolkit);
                window.close();
              } else {
                router.push("/workspace/connections");
              }
            }, 1500);
            return;
          }
          if (status.status === "failed") {
            setState("failed");
            tellOpener(FAILED_MESSAGE, toolkit);
            clearInterval(timer);
            return;
          }
        } catch {
          /* retry */
        }
        if (attempts >= 15) {
          setState("failed");
          tellOpener(FAILED_MESSAGE, toolkit);
          clearInterval(timer);
        }
      })();
    }, 2000);
    return () => clearInterval(timer);
  }, [toolkit, router, params]);

  if (state === "polling") {
    return (
      <div className="flex h-screen items-center justify-center">
        <p className="text-muted-foreground">
          Completing connection to {toolkit}…
        </p>
      </div>
    );
  }
  if (state === "connected") {
    return (
      <div className="flex h-screen items-center justify-center">
        <p className="text-success">Connected! {account && `(${account})`}</p>
      </div>
    );
  }
  return (
    <div className="flex h-screen items-center justify-center">
      <p className="text-destructive">Connection failed. Please try again.</p>
    </div>
  );
}
