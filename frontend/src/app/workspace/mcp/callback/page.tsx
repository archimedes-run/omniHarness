"use client";

import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";

import { getComposioConnectionStatus } from "@/core/mcp/api";

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
                window.opener.postMessage(
                  { type: "composio_connected", toolkit },
                  "*",
                );
                window.close();
              } else {
                router.push("/workspace/mcp");
              }
            }, 1500);
            return;
          }
          if (status.status === "failed") {
            setState("failed");
            clearInterval(timer);
            return;
          }
        } catch {
          /* retry */
        }
        if (attempts >= 15) {
          setState("failed");
          clearInterval(timer);
        }
      })();
    }, 2000);
    return () => clearInterval(timer);
  }, [toolkit, router]);

  if (state === "polling") {
    return (
      <div className="flex h-screen items-center justify-center">
        <p className="text-stone-600">Completing connection to {toolkit}…</p>
      </div>
    );
  }
  if (state === "connected") {
    return (
      <div className="flex h-screen items-center justify-center">
        <p className="text-emerald-600">
          Connected! {account && `(${account})`}
        </p>
      </div>
    );
  }
  return (
    <div className="flex h-screen items-center justify-center">
      <p className="text-red-500">Connection failed. Please try again.</p>
    </div>
  );
}
