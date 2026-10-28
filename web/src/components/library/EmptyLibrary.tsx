// Library empty state: one line of serif, the drop target, Upload and Try a sample, and the chat bar.
import { ArrowUpFromLine } from "lucide-react";
import { ChatBar } from "@/components/shell/ChatBar";
import { SampleButton, UploadButton } from "./LibraryPanel";

export function EmptyLibrary() {
  return (
    <div className="m-auto flex w-full max-w-[640px] flex-col items-center gap-10 px-6">
      <div className="flex w-full flex-col items-center gap-5 rounded-[28px] border border-dashed border-border-strong px-8 py-14 text-center">
        <span className="inline-flex size-12 items-center justify-center rounded-full bg-secondary" aria-hidden>
          <ArrowUpFromLine className="size-5 text-muted-foreground" strokeWidth={1.75} />
        </span>
        <div className="flex flex-col gap-2">
          <h1 className="type-display text-[34px]">Drop a CSV anywhere</h1>
          <p className="text-[15px] text-muted-foreground">Sherlock cleans it, then answers questions about it.</p>
        </div>
        <div className="flex flex-wrap justify-center gap-2">
          <UploadButton label="Upload CSV" variant="primary" />
          <SampleButton label="Try the Titanic sample" />
        </div>
        <p className="text-[12px] text-muted-foreground">CSV, TSV or TXT up to 50 MB · No account needed</p>
      </div>
      <ChatBar placeholder="Load a CSV to start asking" className="px-0 pb-0" />
    </div>
  );
}
