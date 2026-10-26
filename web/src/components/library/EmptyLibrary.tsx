// Library empty state (UI brief §5.1): the drop zone, Upload, Try with sample, and the pitch.
// The chat bar sits in the same centred column, under the pitch (the design canvas's "Empty library").
import { Upload } from "lucide-react";
import { ChatBar } from "@/components/shell/ChatBar";
import { SampleButton, UploadButton } from "./LibraryPanel";

export function EmptyLibrary() {
  return (
    <div className="m-auto flex w-full flex-col items-center gap-6 px-6 py-12">
      <div className="flex h-[320px] w-full max-w-[640px] flex-col items-center justify-center gap-3.5 rounded-2xl border-2 border-dashed border-border-strong">
        <Upload className="size-6 text-muted-foreground" strokeWidth={1.75} aria-hidden />
        <h1 className="font-serif text-[32px] leading-tight">Drop a CSV anywhere</h1>
        <div className="flex w-60 items-center gap-3 text-[12px] text-muted-foreground" aria-hidden>
          <span className="h-px flex-1 bg-border" /> or <span className="h-px flex-1 bg-border" />
        </div>
        <div className="flex flex-wrap justify-center gap-2.5">
          <UploadButton />
          <SampleButton label="Try with sample (Titanic)" />
        </div>
        <p className="text-[12px] text-muted-foreground">.csv, .tsv or .txt · up to 50 MB</p>
        <p className="max-w-[440px] px-4 text-center text-[12px] text-muted-foreground">
          No sign-up: your CSVs stay with this browser. Clearing its cookies, or another browser, starts an empty library.
        </p>
      </div>
      <p className="max-w-[520px] text-center font-serif text-[18px] leading-snug text-foreground-2">
        Sherlock cleans it, charts it, models it, and tells you what it means. Every number shows its source.
      </p>
      <ChatBar placeholder="Load a CSV to start asking" className="mt-6 px-0 pb-0" />
    </div>
  );
}
