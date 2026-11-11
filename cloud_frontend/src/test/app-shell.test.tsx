import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

const replace = vi.fn();
const signOut = vi.fn(async () => undefined);
let pathname = "/library";
let anonymous = false;

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  usePathname: () => pathname,
}));

vi.mock("@/lib/auth/AuthProvider", () => ({
  useAuth: () => ({
    session: { user: { id: "user-1", email: anonymous ? "" : "reader@bookrag.local", isAnonymous: anonymous }, accessToken: "tok", source: "supabase" },
    loading: false,
    signOut,
  }),
}));

import { AppShell } from "@/components/AppShell";

describe("AppShell", () => {
  it("returns from Library to the last Ask page", () => {
    const documentId = "fedb7c1a-3ee9-4c58-9cfb-4875af378569";
    pathname = `/chat/${documentId}`;
    const view = render(<AppShell><p>Chat body</p></AppShell>);
    pathname = "/library";
    view.rerender(<AppShell><p>Library body</p></AppShell>);
    expect(screen.getByRole("link", { name: "Ask" })).toHaveAttribute("href", `/chat/${documentId}`);
    view.unmount();
    sessionStorage.clear();
    pathname = "/library";
  });

  it("forgets an Ask page when its PDF is no longer in the library", () => {
    const documentId = "fedb7c1a-3ee9-4c58-9cfb-4875af378569";
    sessionStorage.setItem("bookrag-last-chat:user-1", documentId);
    pathname = "/library";
    render(<AppShell><p>Library body</p></AppShell>);
    expect(screen.getByRole("link", { name: "Ask" })).toHaveAttribute("href", `/chat/${documentId}`);
    act(() => {
      window.dispatchEvent(new CustomEvent("bookrag-documents-loaded", {
        detail: { userId: "user-1", documentIds: [] },
      }));
    });
    expect(screen.getByRole("link", { name: "Ask" })).toHaveAttribute("href", "/library#books");
    expect(sessionStorage.getItem("bookrag-last-chat:user-1")).toBeNull();
  });

  it("logs out and returns to sign-in", async () => {
    const user = userEvent.setup();
    render(
      <AppShell>
        <p>Library body</p>
      </AppShell>,
    );
    expect(screen.getByText("reader@bookrag.local")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Ask" })).toHaveAttribute("href", "/library#books");
    await user.click(screen.getByRole("button", { name: /log out/i }));
    expect(signOut).toHaveBeenCalled();
    expect(replace).toHaveBeenCalledWith("/login");
  });

  it("warns a guest before losing access to the library", async () => {
    anonymous = true;
    signOut.mockClear();
    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    const user = userEvent.setup();
    render(<AppShell><p>Guest content</p></AppShell>);
    expect(screen.getByText("Guest library")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /log out/i }));
    expect(confirm).toHaveBeenCalled();
    expect(signOut).not.toHaveBeenCalled();
    confirm.mockReturnValue(true);
    await user.click(screen.getByRole("button", { name: /log out/i }));
    expect(signOut).toHaveBeenCalledTimes(1);
    confirm.mockRestore();
    anonymous = false;
  });
});
