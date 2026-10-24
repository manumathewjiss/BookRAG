"use client";

import { isLocalTestAuth, isMockMode, isSupabaseConfigured } from "@/lib/config";

export function MockBanner() {
  if (!isMockMode() && !isLocalTestAuth()) return null;
  return (
    <div className="mock-banner" role="status">
      {isMockMode() ? (
        <><strong>Mock API.</strong> Isolated frontend responses — not live BookRAG retrieval.
          {isSupabaseConfigured() ? " Supabase Auth is live." : " Auth is also local until Supabase keys are set."}</>
      ) : (
        <><strong>Local integration test.</strong> Real FastAPI routes with simulated auth, storage, and AI providers. No cloud calls.</>
      )}
    </div>
  );
}
