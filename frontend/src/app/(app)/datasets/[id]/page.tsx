"use client";

import { ArrowLeft, Trash2 } from "lucide-react";
import Link from "next/link";
import { useParams, useRouter } from "next/navigation";
import { useState } from "react";

import {
  DatasetConversations,
  StartConversationButton,
} from "@/components/analysis/dataset-conversations";
import { DataPreview } from "@/components/datasets/data-preview";
import { ProfileTable } from "@/components/datasets/profile-table";
import { QualityWarnings } from "@/components/datasets/quality-warnings";
import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { ConfirmDialog } from "@/components/ui/confirm-dialog";
import { Spinner } from "@/components/ui/spinner";
import { Tabs } from "@/components/ui/tabs";
import { ApiError } from "@/lib/api/errors";
import { useDataset, useDeleteDataset } from "@/lib/datasets/api";
import { formatDateTime, formatInteger, formatPercent } from "@/lib/format";

export default function DatasetPage() {
  const { id } = useParams<{ id: string }>();
  const router = useRouter();
  const dataset = useDataset(id);
  const remove = useDeleteDataset();
  const [tab, setTab] = useState("profile");
  const [confirming, setConfirming] = useState(false);

  if (dataset.isPending) {
    return (
      <p className="flex items-center gap-2 text-slate">
        <Spinner size={16} label="" /> Loading dataset…
      </p>
    );
  }
  if (dataset.isError) {
    const missing = dataset.error instanceof ApiError && dataset.error.status === 404;
    return (
      <div className="max-w-xl">
        <Alert
          tone={missing ? "info" : "danger"}
          title={missing ? "Dataset not found" : "The dataset couldn't be loaded"}
          action={
            missing ? null : (
              <Button variant="secondary" size="sm" onClick={() => dataset.refetch()}>
                Try again
              </Button>
            )
          }
        >
          {missing ? "It may have been deleted." : dataset.error.message}{" "}
          <Link href="/datasets" className="font-medium text-primary underline underline-offset-2">
            Back to datasets
          </Link>
        </Alert>
      </div>
    );
  }

  const data = dataset.data;
  const { profile } = data;
  const totalCells = profile.row_count * profile.column_count;
  const facts = [
    { label: "Rows", value: formatInteger(profile.row_count) },
    { label: "Columns", value: formatInteger(profile.column_count) },
    {
      label: "Missing cells",
      value: totalCells ? formatPercent(profile.missing_cell_count / totalCells) : "0%",
    },
    { label: "Duplicate rows", value: formatInteger(profile.duplicate_row_count) },
  ];

  return (
    <div className="max-w-6xl">
      <Link
        href="/datasets"
        className="inline-flex items-center gap-1.5 text-sm text-slate hover:text-ink"
      >
        <ArrowLeft size={14} aria-hidden="true" /> Datasets
      </Link>
      <div className="mt-3 flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight break-words">{data.name}</h1>
          <p className="mt-1 text-sm text-slate">
            {data.original_filename}
            {data.sheet_name ? `, sheet ${data.sheet_name}` : ""}. Uploaded{" "}
            {formatDateTime(data.created_at)}.
          </p>
        </div>
        <div className="flex flex-wrap items-start gap-2">
          <StartConversationButton datasetId={data.id} />
          <Button variant="secondary" onClick={() => setConfirming(true)}>
            <Trash2 size={15} aria-hidden="true" />
            Delete
          </Button>
        </div>
      </div>

      <dl className="mt-6 grid grid-cols-2 gap-x-8 gap-y-4 sm:grid-cols-4">
        {facts.map((fact) => (
          <div key={fact.label} className="border-l-2 border-rule-strong pl-3">
            <dt className="text-sm text-slate">{fact.label}</dt>
            <dd className="tabular text-lg font-semibold">{fact.value}</dd>
          </div>
        ))}
      </dl>

      <div className="mt-8">
        <DatasetConversations datasetId={data.id} />
      </div>

      <div className="mt-10">
        <Tabs
          label="Dataset views"
          active={tab}
          onChange={setTab}
          tabs={[
            {
              id: "profile",
              label: "Profile",
              content: (
                <div className="space-y-8">
                  <QualityWarnings warnings={profile.warnings} columns={profile.columns} />
                  <section aria-labelledby="columns-heading">
                    <h2 id="columns-heading" className="mb-3 text-base font-semibold">
                      Columns
                    </h2>
                    <ProfileTable columns={profile.columns} />
                  </section>
                </div>
              ),
            },
            {
              id: "rows",
              label: "Rows",
              content: <DataPreview datasetId={data.id} columns={profile.columns} />,
            },
          ]}
        />
      </div>

      <ConfirmDialog
        open={confirming}
        title="Delete this dataset?"
        confirmLabel="Delete dataset"
        pending={remove.isPending}
        onCancel={() => setConfirming(false)}
        onConfirm={() =>
          remove.mutate(data.id, {
            onSuccess: () => router.replace("/datasets"),
          })
        }
      >
        <p>
          {data.name}, its stored file and every conversation about it will be permanently
          removed. This can&apos;t be undone.
        </p>
        {remove.isError ? (
          <p className="mt-2 text-danger">{remove.error.message}</p>
        ) : null}
      </ConfirmDialog>
    </div>
  );
}
