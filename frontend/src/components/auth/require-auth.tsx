"use client";

import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";
import { ApiError } from "@/lib/api/errors";
import { useCurrentUser } from "@/lib/auth/hooks";
import { loginPathFor } from "@/lib/auth/redirect";

/**
 * Renders children only for a signed-in user. This is a UX guard; the backend authorizes every
 * request independently.
 */
export function RequireAuth({ children }: { children: React.ReactNode }) {
  const user = useCurrentUser();
  const router = useRouter();
  const pathname = usePathname();
  const unauthenticated = user.error instanceof ApiError && user.error.status === 401;

  useEffect(() => {
    if (unauthenticated) router.replace(loginPathFor(pathname));
  }, [unauthenticated, pathname, router]);

  if (user.isPending || unauthenticated) {
    return (
      <div className="flex min-h-dvh items-center justify-center text-slate">
        <Spinner label="Checking your session" />
      </div>
    );
  }

  if (user.isError) {
    return (
      <div className="mx-auto max-w-md px-4 py-16">
        <Alert
          tone="danger"
          title="Couldn't check your session"
          action={
            <Button variant="secondary" size="sm" onClick={() => user.refetch()}>
              Try again
            </Button>
          }
        >
          {user.error.message}
        </Alert>
      </div>
    );
  }

  return children;
}
