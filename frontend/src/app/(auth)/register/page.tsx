import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthForm } from "@/components/auth/auth-form";

export const metadata: Metadata = { title: "Create account" };

export default function RegisterPage() {
  return (
    <>
      <h1 className="text-2xl font-semibold tracking-tight">Create an account</h1>
      <p className="mt-1.5 mb-7 text-slate">
        Upload datasets and keep your analyses in one place. Only you can see them.
      </p>
      <Suspense>
        <AuthForm mode="register" />
      </Suspense>
    </>
  );
}
