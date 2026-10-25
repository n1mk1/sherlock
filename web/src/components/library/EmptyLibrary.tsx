// Library empty state (UI brief §5.1): the drop zone, Upload, Try with sample, and the pitch.
import { Upload } from "lucide-react";
import { SampleButton, UploadButton } from "./LibraryPanel";

export function EmptyLibrary() {
  return (
    <div className="mx-auto flex w-full max-w-[640px] flex-col items-center gap-8 px-4 py-16">
      <div className="flex h-[320px] w-full flex-col items-center justify-center gap-4 rounded-2xl border-2 border-dashed border-border-strong">
        <Upload className="size-6 text-muted-foreground" aria-hidden />
        <h1 className="font-serif text-[32px] leading-tight">Drop a CSV anywhere</h1>
        <div className="flex w-56 items-center gap-3 text-[13px] text-muted-foreground" aria-hidden>
          <span className="h-px flex-1 bg-border" /> or <span className="h-px flex-1 bg-border" />
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          <UploadButton />
          <SampleButton label="Try with sample (Titanic)" />
        </div>
        <p className="text-[12px] text-muted-foreground">.csv, .tsv or .txt · up to 50 MB</p>
      </div>
      <p className="max-w-[460px] text-center font-serif text-[18px] leading-snug text-foreground-2">
        Sherlock cleans it, charts it, models it, and tells you what it means. Every number shows its source.
      </p>
    </div>
  );
}
