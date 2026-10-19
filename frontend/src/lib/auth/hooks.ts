"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type User = components["schemas"]["UserResponse"];
type Credentials = { email: string; password: string };

export const currentUserKey = ["auth", "me"] as const;

export function useCurrentUser() {
  return useQuery({
    queryKey: currentUserKey,
    queryFn: () => unwrap(api.GET("/api/auth/me")),
    retry: false,
    staleTime: 5 * 60_000,
  });
}

export function useLogin() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Credentials) => unwrap(api.POST("/api/auth/login", { body })),
    onSuccess: (user) => {
      // A different user may have been signed in on this browser: drop everything cached.
      queryClient.clear();
      queryClient.setQueryData(currentUserKey, user);
    },
  });
}

export function useRegister() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (body: Credentials) => unwrap(api.POST("/api/auth/register", { body })),
    onSuccess: (user) => {
      queryClient.clear();
      queryClient.setQueryData(currentUserKey, user);
    },
  });
}

export function useLogout() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: () => unwrap(api.POST("/api/auth/logout")),
    onSettled: () => {
      queryClient.clear();
    },
  });
}
