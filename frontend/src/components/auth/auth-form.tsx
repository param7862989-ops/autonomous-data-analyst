"use client";

import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/text-field";
import { ApiError } from "@/lib/api/errors";
import { useLogin, useRegister } from "@/lib/auth/hooks";
import { safeNextPath } from "@/lib/auth/redirect";

const EMAIL_PATTERN = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
export const PASSWORD_MIN_LENGTH = 10;

type Mode = "login" | "register";
type FieldErrors = { email?: string; password?: string };

function validate(mode: Mode, email: string, password: string): FieldErrors {
  const errors: FieldErrors = {};
  if (!EMAIL_PATTERN.test(email.trim())) errors.email = "Enter an email address like name@example.com.";
  if (mode === "register") {
    if (password.length < PASSWORD_MIN_LENGTH) {
      errors.password = `Use at least ${PASSWORD_MIN_LENGTH} characters.`;
    } else if (password.length > 128) {
      errors.password = "Use 128 characters or fewer.";
    }
  } else if (!password) {
    errors.password = "Enter your password.";
  }
  return errors;
}

function serverMessage(error: unknown): string {
  if (!(error instanceof ApiError)) return "Something went wrong. Try again.";
  if (error.code === "validation_error") return "Check the email and password and try again.";
  return error.message;
}

export function AuthForm({ mode }: { mode: Mode }) {
  const router = useRouter();
  const searchParams = useSearchParams();
  const login = useLogin();
  const register = useRegister();
  const mutation = mode === "login" ? login : register;

  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});

  const isLogin = mode === "login";
  const submitLabel = isLogin ? "Sign in" : "Create account";

  function onSubmit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const errors = validate(mode, email, password);
    setFieldErrors(errors);
    if (errors.email || errors.password) return;
    mutation.mutate(
      { email: email.trim(), password },
      { onSuccess: () => router.replace(safeNextPath(searchParams.get("next"))) },
    );
  }

  return (
    <form onSubmit={onSubmit} noValidate className="space-y-5">
      {mutation.isError ? <Alert tone="danger">{serverMessage(mutation.error)}</Alert> : null}
      <TextField
        label="Email"
        type="email"
        name="email"
        autoComplete="email"
        value={email}
        onChange={(event) => setEmail(event.target.value)}
        error={fieldErrors.email}
        required
      />
      <TextField
        label="Password"
        type="password"
        name="password"
        autoComplete={isLogin ? "current-password" : "new-password"}
        value={password}
        onChange={(event) => setPassword(event.target.value)}
        hint={isLogin ? undefined : `At least ${PASSWORD_MIN_LENGTH} characters.`}
        error={fieldErrors.password}
        required
      />
      <Button type="submit" className="w-full" pending={mutation.isPending}>
        {submitLabel}
      </Button>
      <p className="text-center text-sm text-slate">
        {isLogin ? "New here? " : "Already have an account? "}
        <Link
          href={isLogin ? "/register" : "/login"}
          className="font-medium text-primary underline-offset-2 hover:underline"
        >
          {isLogin ? "Create an account" : "Sign in"}
        </Link>
      </p>
    </form>
  );
}
