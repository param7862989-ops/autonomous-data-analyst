"use client";

import { clsx } from "clsx";
import { FileSpreadsheet, Upload, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useId, useRef, useState } from "react";

import { Alert } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { TextField } from "@/components/ui/text-field";
import { ApiError } from "@/lib/api/errors";
import { useUploadDataset, useUploadLimits } from "@/lib/datasets/api";
import { formatBytes } from "@/lib/format";

const DEFAULT_EXTENSIONS = [".csv", ".tsv", ".txt", ".xlsx"];
const DEFAULT_MAX_BYTES = 25 * 1024 * 1024;

function extensionOf(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot === -1 ? "" : name.slice(dot).toLowerCase();
}

export function validateFile(
  file: File,
  accepted: string[] = DEFAULT_EXTENSIONS,
  maxBytes: number = DEFAULT_MAX_BYTES,
): string | null {
  if (!accepted.includes(extensionOf(file.name))) {
    return "Choose a .csv or .xlsx file.";
  }
  if (file.size === 0) return "This file is empty.";
  if (file.size > maxBytes) {
    return `This file is ${formatBytes(file.size)}; the limit is ${formatBytes(maxBytes)}.`;
  }
  return null;
}

function sheetsFrom(error: unknown): string[] | null {
  if (!(error instanceof ApiError)) return null;
  if (error.code !== "sheet_required" && error.code !== "sheet_not_found") return null;
  const sheets = (error.details as { sheets?: unknown } | null)?.sheets;
  return Array.isArray(sheets) && sheets.every((s) => typeof s === "string") ? sheets : null;
}

export function UploadPanel() {
  const router = useRouter();
  const limits = useUploadLimits();
  const upload = useUploadDataset();
  const inputRef = useRef<HTMLInputElement>(null);
  const inputId = useId();

  const [file, setFile] = useState<File | null>(null);
  const [name, setName] = useState("");
  const [fileError, setFileError] = useState<string | null>(null);
  const [sheets, setSheets] = useState<string[] | null>(null);
  const [sheet, setSheet] = useState("");
  const [dragging, setDragging] = useState(false);

  const accepted = limits.data?.accepted_extensions ?? DEFAULT_EXTENSIONS;
  const maxBytes = limits.data?.max_upload_bytes ?? DEFAULT_MAX_BYTES;

  function choose(selected: File | null) {
    upload.reset();
    setSheets(null);
    setSheet("");
    setFile(selected);
    setFileError(selected ? validateFile(selected, accepted, maxBytes) : null);
  }

  function submit(event: React.FormEvent) {
    event.preventDefault();
    if (!file) {
      setFileError("Choose a file to upload.");
      return;
    }
    const problem = validateFile(file, accepted, maxBytes);
    setFileError(problem);
    if (problem) return;
    upload.mutate(
      { file, name, sheetName: sheets ? sheet : undefined },
      {
        onSuccess: (dataset) => router.push(`/datasets/${dataset.id}`),
        onError: (error) => {
          const found = sheetsFrom(error);
          if (found) {
            setSheets(found);
            setSheet((current) => (found.includes(current) ? current : found[0]));
          }
        },
      },
    );
  }

  const needsSheet = sheets !== null;
  const serverError = upload.isError && !needsSheet ? upload.error : null;

  return (
    <form onSubmit={submit} noValidate className="space-y-5" aria-labelledby={`${inputId}-title`}>
      <div>
        <h2 id={`${inputId}-title`} className="text-base font-semibold">
          Upload a dataset
        </h2>
        <p className="mt-1 text-sm text-slate">
          CSV or Excel (.xlsx), up to {formatBytes(maxBytes)}. The first row must contain column
          names.
        </p>
      </div>

      <div
        onDragOver={(event) => {
          event.preventDefault();
          setDragging(true);
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(event) => {
          event.preventDefault();
          setDragging(false);
          choose(event.dataTransfer.files.item(0));
        }}
        className={clsx(
          "rounded-(--radius-panel) border-2 border-dashed bg-surface px-4 py-6 text-center",
          dragging ? "border-primary bg-primary-soft" : "border-rule-strong",
        )}
      >
        <input
          ref={inputRef}
          id={inputId}
          type="file"
          accept={accepted.join(",")}
          className="sr-only"
          aria-describedby={fileError ? `${inputId}-error` : undefined}
          onChange={(event) => choose(event.target.files?.item(0) ?? null)}
        />
        {file ? (
          <div className="flex items-center justify-between gap-3 text-left">
            <span className="flex min-w-0 items-center gap-2.5">
              <FileSpreadsheet size={20} aria-hidden="true" className="shrink-0 text-slate" />
              <span className="min-w-0">
                <span className="block truncate font-medium">{file.name}</span>
                <span className="block text-sm text-slate">{formatBytes(file.size)}</span>
              </span>
            </span>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={() => {
                choose(null);
                if (inputRef.current) inputRef.current.value = "";
              }}
            >
              <X size={14} aria-hidden="true" />
              Remove
            </Button>
          </div>
        ) : (
          <label htmlFor={inputId} className="flex cursor-pointer flex-col items-center gap-2">
            <Upload size={22} aria-hidden="true" className="text-slate" />
            <span>
              <span className="font-medium text-primary underline underline-offset-2">
                Choose a file
              </span>{" "}
              <span className="text-slate">or drop it here</span>
            </span>
          </label>
        )}
      </div>
      {fileError ? (
        <p id={`${inputId}-error`} className="-mt-3 text-sm text-danger">
          {fileError}
        </p>
      ) : null}

      {needsSheet ? (
        <fieldset className="rounded-(--radius-panel) border border-rule bg-surface px-4 py-3">
          <legend className="px-1 text-sm font-medium">
            This workbook has several sheets. Choose one to import.
          </legend>
          <div className="mt-1 flex flex-wrap gap-x-5 gap-y-2">
            {sheets.map((option) => (
              <label key={option} className="flex items-center gap-2 text-sm">
                <input
                  type="radio"
                  name="sheet"
                  value={option}
                  checked={sheet === option}
                  onChange={() => setSheet(option)}
                  className="accent-primary"
                />
                {option}
              </label>
            ))}
          </div>
        </fieldset>
      ) : null}

      <TextField
        label="Name (optional)"
        value={name}
        maxLength={255}
        onChange={(event) => setName(event.target.value)}
        hint="Defaults to the file name."
      />

      {serverError ? (
        <Alert tone="danger" title="The file couldn't be imported">
          {serverError.message}
        </Alert>
      ) : null}

      <Button type="submit" pending={upload.isPending} disabled={Boolean(fileError)}>
        {upload.isPending ? "Uploading and profiling…" : needsSheet ? "Import sheet" : "Upload"}
      </Button>
    </form>
  );
}
