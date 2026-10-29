import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
const search = new URLSearchParams("next=/chat/doc-9&reason=expired");

vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => search,
  usePathname: () => "/login",
}));

vi.mock("@/lib/auth/AuthProvider", () => ({
  useAuth: () => ({
    signIn: vi.fn(),
    signUp: vi.fn(),
    session: null,
    loading: false,
  }),
}));

import { AuthForm } from "@/components/AuthForm";

describe("AuthForm", () => {
  beforeEach(() => {
    replace.mockReset();
  });

  it("keeps the post-login path and explains an expired session", () => {
    render(<AuthForm mode="login" />);
    expect(screen.getByText(/Your session ended/)).toBeInTheDocument();
    const signup = screen.getByRole("link", { name: /sign up/i });
    expect(signup.getAttribute("href")).toBe("/signup?next=%2Fchat%2Fdoc-9");
  });
});
