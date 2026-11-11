import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const replace = vi.fn();
const signInGuest = vi.fn(async () => undefined);

vi.mock("next/navigation", () => ({ useRouter: () => ({ replace }) }));
vi.mock("@/lib/auth/AuthProvider", () => ({ useAuth: () => ({ signInGuest }) }));

import { GuestAccessButton } from "@/components/GuestAccessButton";

describe("guest access", () => {
  beforeEach(() => { replace.mockReset(); signInGuest.mockReset(); signInGuest.mockResolvedValue(undefined); });

  it("creates the guest session before navigating to the requested page", async () => {
    const user = userEvent.setup();
    render(<GuestAccessButton nextPath="/chat/ready-pdf" />);
    await user.click(screen.getByRole("button", { name: "Continue as guest" }));
    expect(signInGuest).toHaveBeenCalledTimes(1);
    expect(replace).toHaveBeenCalledWith("/chat/ready-pdf");
  });

  it("shows a guest sign-in error without navigating", async () => {
    signInGuest.mockRejectedValueOnce(new Error("Guest access is disabled."));
    const user = userEvent.setup();
    render(<GuestAccessButton />);
    await user.click(screen.getByRole("button", { name: "Continue as guest" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Guest access is disabled.");
    expect(replace).not.toHaveBeenCalled();
  });
});
