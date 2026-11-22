"use client";

import {
  type QueryClient,
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { useEffect, useState } from "react";

import { api, unwrap } from "@/lib/api/client";
import type { components } from "@/lib/api/schema";

export type ServerConfig = components["schemas"]["ServerConfig"];
export type ConversationSummary = components["schemas"]["ConversationSummary"];
export type ConversationDetail = components["schemas"]["ConversationDetail"];
export type RunSummary = components["schemas"]["RunSummary"];
export type RunDetail = components["schemas"]["RunDetail"];
export type HistoryItem = components["schemas"]["HistoryItem"];
export type ActivityEvent = components["schemas"]["ActivityEventOut"];
export type AgentOutcome = components["schemas"]["AgentOutcome"];
export type StoredResult = components["schemas"]["StoredResult"];
export type ChartSpec = components["schemas"]["ChartSpec"];
export type FinalAnswer = components["schemas"]["FinalAnswer"];
export type Finding = components["schemas"]["Finding"];
export type RunStatus = RunSummary["status"];

export const ACTIVE_STATUSES: RunStatus[] = ["queued", "running"];
export const isActive = (status: RunStatus) => ACTIVE_STATUSES.includes(status);

export const analysisKeys = {
  config: ["config"] as const,
  conversations: (datasetId?: string) => ["conversations", "list", datasetId ?? "all"] as const,
  conversation: (id: string) => ["conversations", "detail", id] as const,
  run: (id: string) => ["analyses", "detail", id] as const,
  history: (datasetId?: string) => ["analyses", "history", datasetId ?? "all"] as const,
};

export function useServerConfig() {
  return useQuery({
    queryKey: analysisKeys.config,
    queryFn: () => unwrap(api.GET("/api/config")),
    staleTime: 5 * 60_000,
  });
}

export function useConversations(datasetId?: string, limit = 50, offset = 0) {
  return useQuery({
    queryKey: [...analysisKeys.conversations(datasetId), limit, offset],
    queryFn: () =>
      unwrap(
        api.GET("/api/conversations", {
          params: { query: { limit, offset, ...(datasetId ? { dataset_id: datasetId } : {}) } },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

export function useConversation(id: string) {
  return useQuery({
    queryKey: analysisKeys.conversation(id),
    queryFn: () =>
      unwrap(
        api.GET("/api/conversations/{conversation_id}", {
          params: { path: { conversation_id: id } },
        }),
      ),
  });
}

function refreshAfterFinish(queryClient: QueryClient, run: RunDetail) {
  // The conversation's run summaries and the history now have a final state.
  void queryClient.invalidateQueries({ queryKey: analysisKeys.conversation(run.conversation_id) });
  void queryClient.invalidateQueries({ queryKey: ["analyses", "history"] });
  void queryClient.invalidateQueries({ queryKey: ["conversations", "list"] });
}

/**
 * Follows a run while it is queued or running: over a Server-Sent Events stream when it is
 * connected, otherwise by polling once a second. The stream writes into the same query cache,
 * so components cannot tell the two apart. If the stream fails or the server ends it early
 * (limit, lifetime), polling takes over for the rest of the run.
 */
export function useRun(id: string) {
  const queryClient = useQueryClient();
  const [streaming, setStreaming] = useState(false);
  const query = useQuery({
    queryKey: analysisKeys.run(id),
    queryFn: async () => {
      const run = await unwrap(
        api.GET("/api/analyses/{run_id}", { params: { path: { run_id: id } } }),
      );
      if (!isActive(run.status)) refreshAfterFinish(queryClient, run);
      return run;
    },
    refetchInterval: (q) => {
      const status = q.state.data?.status;
      return status && isActive(status) && !streaming ? 1000 : false;
    },
    staleTime: (q) => (q.state.data && !isActive(q.state.data.status) ? Infinity : 0),
  });

  const active = query.data ? isActive(query.data.status) : false;
  useEffect(() => {
    if (!active || typeof EventSource === "undefined") return;
    const source = new EventSource(`/api/analyses/${encodeURIComponent(id)}/events`);
    const stop = () => {
      source.close();
      setStreaming(false);
    };
    source.onopen = () => setStreaming(true);
    source.addEventListener("run", (event) => {
      const run = JSON.parse((event as MessageEvent<string>).data) as RunDetail;
      queryClient.setQueryData(analysisKeys.run(id), run);
      if (!isActive(run.status)) {
        stop();
        refreshAfterFinish(queryClient, run);
      }
    });
    // "end" (limit, lifetime, signed out) or a network error: poll instead. EventSource would
    // reconnect by itself; closing it keeps a broken proxy from causing a reconnect loop.
    source.addEventListener("end", stop);
    source.onerror = stop;
    return stop;
  }, [active, id, queryClient]);

  return query;
}

export function useHistory(datasetId?: string, limit = 50, offset = 0) {
  return useQuery({
    queryKey: [...analysisKeys.history(datasetId), limit, offset],
    queryFn: () =>
      unwrap(
        api.GET("/api/analyses", {
          params: { query: { limit, offset, ...(datasetId ? { dataset_id: datasetId } : {}) } },
        }),
      ),
    placeholderData: keepPreviousData,
    // A listed run can finish while the list is on screen.
    refetchInterval: (q) =>
      q.state.data?.items.some((item) => isActive(item.status)) ? 5000 : false,
  });
}

export function useCreateConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (datasetId: string) =>
      unwrap(api.POST("/api/conversations", { body: { dataset_id: datasetId } })),
    onSuccess: (conversation) => {
      queryClient.setQueryData(analysisKeys.conversation(conversation.id), conversation);
      void queryClient.invalidateQueries({ queryKey: ["conversations", "list"] });
    },
  });
}

export function useAskQuestion(conversationId: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (question: string) =>
      unwrap(
        api.POST("/api/conversations/{conversation_id}/analyses", {
          params: { path: { conversation_id: conversationId } },
          body: { question },
        }),
      ),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: analysisKeys.conversation(conversationId) });
      void queryClient.invalidateQueries({ queryKey: ["conversations", "list"] });
      void queryClient.invalidateQueries({ queryKey: ["analyses", "history"] });
    },
  });
}

export function useCancelRun() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (runId: string) =>
      unwrap(api.POST("/api/analyses/{run_id}/cancel", { params: { path: { run_id: runId } } })),
    onSuccess: (run) => {
      void queryClient.invalidateQueries({ queryKey: analysisKeys.run(run.id) });
    },
  });
}

export function useDeleteConversation() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(
        api.DELETE("/api/conversations/{conversation_id}", {
          params: { path: { conversation_id: id } },
        }),
      ),
    onSuccess: () => {
      // Mark stale without refetching: the caller is leaving the deleted conversation's page,
      // and refetching it there would flash "not found". Every view refetches when next shown.
      void queryClient.invalidateQueries({ queryKey: ["conversations"], refetchType: "none" });
      void queryClient.invalidateQueries({ queryKey: ["analyses"], refetchType: "none" });
    },
  });
}

export function useRenameConversation(id: string) {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (title: string) =>
      unwrap(
        api.PATCH("/api/conversations/{conversation_id}", {
          params: { path: { conversation_id: id } },
          body: { title },
        }),
      ),
    onSuccess: (conversation) => {
      queryClient.setQueryData(analysisKeys.conversation(id), conversation);
      void queryClient.invalidateQueries({ queryKey: ["conversations", "list"] });
    },
  });
}
