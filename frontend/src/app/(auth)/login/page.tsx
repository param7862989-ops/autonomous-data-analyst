import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthForm } from "@/components/auth/auth-form";

export const metadata: Metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight">Sign in</h1>
      <p className="mt-1.5 mb-7 text-slate">Your datasets and analyses are private to your account.</p>
      {/* useSearchParams (for ?next=) needs a Suspense boundary on a prerendered page. */}
      <Suspense>
        <AuthForm mode="login" />
      </Suspense>
    </>
  );
}
