import { Suspense } from "react";
import { AuthForm } from "@/components/AuthForm";

export default function LoginPage() {
  return (
    <Suspense fallback={<p className="status">Loading sign-in…</p>}>
      <AuthForm mode="login" />
    </Suspense>
  );
}
