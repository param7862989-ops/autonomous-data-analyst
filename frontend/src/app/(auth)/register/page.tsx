import type { Metadata } from "next";
import { Suspense } from "react";

import { AuthForm } from "@/components/auth/auth-form";

export const metadata: Metadata = { title: "Create account" };

export default function RegisterPage() {
  return (
    <>
      <h1 className="text-[1.625rem] leading-tight">Create an account</h1>
      <p className="mt-2 mb-7 text-slate">
        Your datasets and answers stay in your account. No one else can see them.
      </p>
      <Suspense>
        <AuthForm mode="register" />
      </Suspense>
    </>
  );
}
