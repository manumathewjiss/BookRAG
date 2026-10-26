import { Suspense } from "react";
import { AuthForm } from "@/components/AuthForm";

export default function SignupPage() {
  return (
    <Suspense fallback={<p className="status">Loading sign-up…</p>}>
      <AuthForm mode="signup" />
    </Suspense>
  );
}
