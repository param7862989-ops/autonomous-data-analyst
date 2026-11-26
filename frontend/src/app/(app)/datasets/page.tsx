import type { Metadata } from "next";

import { DatasetList } from "@/components/datasets/dataset-list";
import { UploadPanel } from "@/components/datasets/upload-panel";
import { PageHeader, Section } from "@/components/ui/page";

export const metadata: Metadata = { title: "Datasets" };

export default function DatasetsPage() {
  return (
    <div>
      <PageHeader
        title="Datasets"
        lead="Uploads are checked and profiled straight away. Only you can see them."
      />
      <Section label="Your datasets" id="your-datasets">
        <DatasetList />
      </Section>
      <Section label="Upload a dataset" id="upload-heading" className="border-b-0">
        <UploadPanel labelledBy="upload-heading" />
      </Section>
    </div>
  );
}
