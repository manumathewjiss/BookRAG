"use client";

import { useCallback } from "react";
import { useRouter } from "next/navigation";
import { errorMessage, isUnauthorized } from "@/lib/api";
import { useAuth } from "@/lib/auth/AuthProvider";

export function useApiGuard() {
  const { signOut } = useAuth();
  const router = useRouter();

  return useCallback(
    async (err: unknown): Promise<string> => {
      if (isUnauthorized(err)) {
        await signOut();
        router.replace("/login?reason=expired");
        return "Your session ended. Sign in again.";
      }
      return errorMessage(err);
    },
    [router, signOut],
  );
}
