"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/lib/auth/AuthProvider";
import { safeNextPath } from "@/lib/config";

export function GuestAccessButton({ nextPath = "/library", className = "" }: {
  nextPath?: string;
  className?: string;
}) {
  const { signInGuest } = useAuth();
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  async function continueAsGuest() {
    if (busy) return;
    setBusy(true);
    setError("");
    try {
      await signInGuest();
      router.replace(safeNextPath(nextPath));
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : "Guest access is unavailable right now.");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="guest-access">
      <button type="button" className={className} disabled={busy} onClick={() => void continueAsGuest()}>
        {busy ? "Opening your library…" : "Continue as guest"}
      </button>
      {error && <p className="error-card" role="alert">{error}</p>}
    </div>
  );
}
