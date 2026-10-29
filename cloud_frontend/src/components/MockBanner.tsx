"use client";

import { isLocalTestAuth, isMockMode, isSupabaseConfigured } from "@/lib/config";

export function MockBanner() {
  if (isMockMode()) {
    return (
      <div className="mock-banner" role="status">
        <strong>Mock API.</strong> Isolated frontend responses — not live BookRAG retrieval.
        {isSupabaseConfigured()
          ? " Supabase Auth is live."
          : " Auth is also local until Supabase keys are set."}
      </div>
    );
  }
  if (isLocalTestAuth() && !isSupabaseConfigured()) {
    return (
      <div className="mock-banner" role="status">
        <strong>Local test auth.</strong> Simulated sign-in for a local API. Do not enable on Vercel.
      </div>
    );
  }
  return null;
}
