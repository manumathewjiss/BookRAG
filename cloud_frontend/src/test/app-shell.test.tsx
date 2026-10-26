import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const replace = vi.fn();
const signOut = vi.fn(async () => undefined);

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => "/library",
}));

vi.mock("@/lib/auth/AuthProvider", () => ({
  useAuth: () => ({
    session: { user: { id: "user-1", email: "reader@bookrag.local" }, accessToken: "tok", source: "supabase" },
    loading: false,
    signOut,
  }),
}));

import { AppShell } from "@/components/AppShell";

describe("AppShell", () => {
  it("logs out and returns to sign-in", async () => {
    const user = userEvent.setup();
    render(
      <AppShell>
        <p>Library body</p>
      </AppShell>,
    );
    expect(screen.getByText("reader@bookrag.local")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /log out/i }));
    expect(signOut).toHaveBeenCalled();
    expect(replace).toHaveBeenCalledWith("/login");
  });
});
