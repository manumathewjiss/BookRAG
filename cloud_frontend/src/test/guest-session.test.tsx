import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const guest = vi.hoisted(() => ({
  signInAnonymously: vi.fn(async () => ({
    data: {
      user: { id: "guest-123", email: undefined, is_anonymous: true },
      session: { access_token: "guest-token" },
    },
    error: null,
  })),
}));

vi.mock("@/lib/config", () => ({
  isSupabaseConfigured: () => true,
  isMockMode: () => false,
  isLocalTestAuth: () => false,
  mockEmail: () => "demo@bookrag.local",
}));
vi.mock("@/lib/auth/supabase", () => ({
  createSupabaseBrowser: () => ({ auth: {
    getSession: async () => ({ data: { session: null } }),
    onAuthStateChange: () => ({ data: { subscription: { unsubscribe: vi.fn() } } }),
    signInAnonymously: guest.signInAnonymously,
  } }),
}));

import { AuthProvider, useAuth } from "@/lib/auth/AuthProvider";

function GuestHarness() {
  const { session, signInGuest } = useAuth();
  return <>
    <button onClick={() => void signInGuest()}>Start guest session</button>
    <span>{session?.user.isAnonymous ? "Guest library" : "No guest session"}</span>
    <span>{session?.accessToken || "No token"}</span>
  </>;
}

describe("Supabase guest session", () => {
  it("keeps the anonymous user ID and access token for the normal private API path", async () => {
    const user = userEvent.setup();
    render(<AuthProvider><GuestHarness /></AuthProvider>);
    await user.click(screen.getByRole("button", { name: "Start guest session" }));
    expect(guest.signInAnonymously).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Guest library")).toBeInTheDocument();
    expect(screen.getByText("guest-token")).toBeInTheDocument();
  });
});
