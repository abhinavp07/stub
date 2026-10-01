import { Suspense } from "react";

import { AuthForm } from "@/components/AuthForm";

export const metadata = { title: "Sign up · Receipt Tracker" };

export default function SignupPage() {
  return (
    <Suspense>
      <AuthForm mode="signup" />
    </Suspense>
  );
}
