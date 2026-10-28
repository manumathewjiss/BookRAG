import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

let signedIn = false;

vi.mock("@/lib/auth/AuthProvider", () => ({
  useAuth: () => ({
    session: signedIn ? { user: { id: "user-1" } } : null,
    loading: false,
  }),
}));

import HomePage from "@/app/page";

describe("HomePage account action", () => {
  it("sends visitors to account creation", () => {
    signedIn = false;
    render(<HomePage />);
    expect(screen.getByRole("link", { name: /create an account/i })).toHaveAttribute("href", "/signup");
    expect(screen.getByRole("link", { name: "Sign in" })).toHaveAttribute("href", "/login");
  });

  it("sends signed-in readers to their library", () => {
    signedIn = true;
    render(<HomePage />);
    expect(screen.getByRole("link", { name: /open my library/i })).toHaveAttribute("href", "/library");
    expect(screen.getByRole("link", { name: "My library" })).toHaveAttribute("href", "/library");
    expect(screen.queryByRole("link", { name: /create an account/i })).not.toBeInTheDocument();
  });
});
