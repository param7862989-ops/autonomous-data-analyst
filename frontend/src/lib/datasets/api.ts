"use client";

import { keepPreviousData, useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api, CSRF_HEADER, unwrap } from "@/lib/api/client";
import { networkError, toApiError } from "@/lib/api/errors";
import type { components } from "@/lib/api/schema";

export type DatasetSummary = components["schemas"]["DatasetSummary"];
export type DatasetDetail = components["schemas"]["DatasetDetail"];
export type DatasetPreview = components["schemas"]["DatasetPreview"];
export type ColumnProfile = components["schemas"]["ColumnProfile"];
export type DataQualityWarning = components["schemas"]["DataQualityWarning"];
export type UploadLimits = components["schemas"]["UploadLimits"];
export type SemanticType = ColumnProfile["semantic_type"];

export const datasetKeys = {
  all: ["datasets"] as const,
  list: () => ["datasets", "list"] as const,
  limits: () => ["datasets", "limits"] as const,
  detail: (id: string) => ["datasets", "detail", id] as const,
  preview: (id: string, offset: number, limit: number) =>
    ["datasets", "preview", id, offset, limit] as const,
};

export function useDatasets() {
  return useQuery({
    queryKey: datasetKeys.list(),
    queryFn: () => unwrap(api.GET("/api/datasets", { params: { query: { limit: 100 } } })),
  });
}

export function useUploadLimits() {
  return useQuery({
    queryKey: datasetKeys.limits(),
    queryFn: () => unwrap(api.GET("/api/datasets/limits")),
    staleTime: Infinity,
  });
}

export function useDataset(id: string) {
  return useQuery({
    queryKey: datasetKeys.detail(id),
    // Callers may not know the id yet (e.g. while a conversation loads).
    enabled: Boolean(id),
    queryFn: () =>
      unwrap(api.GET("/api/datasets/{dataset_id}", { params: { path: { dataset_id: id } } })),
  });
}

export function useDatasetPreview(id: string, offset: number, limit: number) {
  return useQuery({
    queryKey: datasetKeys.preview(id, offset, limit),
    queryFn: () =>
      unwrap(
        api.GET("/api/datasets/{dataset_id}/preview", {
          params: { path: { dataset_id: id }, query: { offset, limit } },
        }),
      ),
    placeholderData: keepPreviousData,
  });
}

export type UploadInput = { file: File; sheetName?: string; name?: string };

/**
 * Multipart upload. Uses fetch directly because the generated client types binary fields as
 * strings; errors are normalised the same way as every other API call.
 */
export async function uploadDataset(input: UploadInput): Promise<DatasetDetail> {
  const form = new FormData();
  form.append("file", input.file);
  if (input.sheetName) form.append("sheet_name", input.sheetName);
  if (input.name?.trim()) form.append("name", input.name.trim());
  let response: Response;
  try {
    response = await fetch(new URL("/api/datasets", window.location.origin), {
      method: "POST",
      body: form,
      credentials: "same-origin",
      headers: CSRF_HEADER,
    });
  } catch {
    throw networkError();
  }
  const body: unknown = await response.json().catch(() => null);
  if (!response.ok) throw toApiError(response.status, body);
  return body as DatasetDetail;
}

export function useUploadDataset() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: uploadDataset,
    onSuccess: (dataset) => {
      queryClient.setQueryData(datasetKeys.detail(dataset.id), dataset);
      void queryClient.invalidateQueries({ queryKey: datasetKeys.list() });
    },
  });
}

export function useDeleteDataset() {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE("/api/datasets/{dataset_id}", { params: { path: { dataset_id: id } } })),
    onSuccess: (_, id) => {
      queryClient.removeQueries({ queryKey: datasetKeys.detail(id) });
      void queryClient.invalidateQueries({ queryKey: datasetKeys.all });
    },
  });
}
