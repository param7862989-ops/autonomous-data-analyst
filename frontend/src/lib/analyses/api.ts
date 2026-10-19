"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

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

export function useConversations(datasetId?: string) {
  return useQuery({
    queryKey: analysisKeys.conversations(datasetId),
    queryFn: () =>
      unwrap(
        api.GET("/api/conversations", {
          params: { query: { limit: 50, ...(datasetId ? { dataset_id: datasetId } : {}) } },
        }),
      ),
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

/** Polls once a second while the run is queued or running, then stops. */
export function useRun(id: string) {
  const queryClient = useQueryClient();
  return useQuery({
    queryKey: analysisKeys.run(id),
    queryFn: async () => {
      const run = await unwrap(
        api.GET("/api/analyses/{run_id}", { params: { path: { run_id: id } } }),
      );
      if (!isActive(run.status)) {
        // The conversation's run summaries and the history now have a final state.
        void queryClient.invalidateQueries({ queryKey: analysisKeys.conversation(run.conversation_id) });
        void queryClient.invalidateQueries({ queryKey: ["analyses", "history"] });
      }
      return run;
    },
    refetchInterval: (query) => {
      const status = query.state.data?.status;
      return status && isActive(status) ? 1000 : false;
    },
    staleTime: (query) => (query.state.data && !isActive(query.state.data.status) ? Infinity : 0),
  });
}

export function useHistory(datasetId?: string, limit = 50) {
  return useQuery({
    queryKey: [...analysisKeys.history(datasetId), limit],
    queryFn: () =>
      unwrap(
        api.GET("/api/analyses", {
          params: { query: { limit, ...(datasetId ? { dataset_id: datasetId } : {}) } },
        }),
      ),
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
    onSuccess: (_, id) => {
      queryClient.removeQueries({ queryKey: analysisKeys.conversation(id) });
      void queryClient.invalidateQueries({ queryKey: ["conversations"] });
      void queryClient.invalidateQueries({ queryKey: ["analyses"] });
    },
  });
}
