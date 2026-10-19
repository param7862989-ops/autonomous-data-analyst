import type { Metadata } from "next";

import { DatasetList } from "@/components/datasets/dataset-list";
import { UploadPanel } from "@/components/datasets/upload-panel";

export const metadata: Metadata = { title: "Datasets" };

export default function DatasetsPage() {
  return (
    <div className="max-w-5xl">
      <h1 className="text-2xl font-semibold tracking-tight">Datasets</h1>
      <p className="mt-2 max-w-[65ch] text-slate">
        Each dataset is validated and profiled when you upload it. Only you can see your datasets.
      </p>
      <div className="mt-8 grid gap-10 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <section aria-labelledby="your-datasets" className="min-w-0">
          <h2 id="your-datasets" className="mb-3 text-base font-semibold">
            Your datasets
          </h2>
          <DatasetList />
        </section>
        <div className="lg:order-none">
          <UploadPanel />
        </div>
      </div>
    </div>
  );
}
