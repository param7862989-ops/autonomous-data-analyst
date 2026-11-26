import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthForm } from "@/components/auth/auth-form";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <>
      <h1 className="text-[1.625rem] leading-tight">Sign in</h1>
      <p className="mt-2 mb-7 text-slate">Your datasets and answers are private to your account.</p>
      {/* useSearchParams (for ?next=) needs a Suspense boundary on a prerendered page. */}
      <Suspense>
        <AuthForm mode="login" />
      </Suspense>
    </>
  );
}
