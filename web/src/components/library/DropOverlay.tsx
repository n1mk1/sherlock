// Drag anywhere (App Flow §3.1): a full-window drop target; the first file goes to the import preview.
import { Upload } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useUi } from "@/state/ui";

function hasFiles(e: DragEvent) {
  return Array.from(e.dataTransfer?.types ?? []).includes("Files");
}

export function DropOverlay() {
  const [over, setOver] = useState(false);
  const depth = useRef(0);
  useEffect(() => {
    const enter = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth.current += 1;
      setOver(true);
    };
    const leave = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      depth.current = Math.max(0, depth.current - 1);
      if (!depth.current) setOver(false);
    };
    const overHandler = (e: DragEvent) => {
      if (hasFiles(e)) e.preventDefault();
    };
    const drop = (e: DragEvent) => {
      if (!hasFiles(e)) return;
      e.preventDefault();
      depth.current = 0;
      setOver(false);
      const files = Array.from(e.dataTransfer?.files ?? []);
      if (!files.length) return;
      if (files.length > 1) toast("Imported the first file; drop the others one at a time.");
      useUi.getState().openImport(files[0]);
    };
    window.addEventListener("dragenter", enter);
    window.addEventListener("dragleave", leave);
    window.addEventListener("dragover", overHandler);
    window.addEventListener("drop", drop);
    return () => {
      window.removeEventListener("dragenter", enter);
      window.removeEventListener("dragleave", leave);
      window.removeEventListener("dragover", overHandler);
      window.removeEventListener("drop", drop);
    };
  }, []);
  if (!over) return null;
  return (
    <div className="pointer-events-none fixed inset-3 z-40 flex flex-col items-center justify-center gap-3 rounded-2xl border-2 border-dashed border-accent bg-accent-soft">
      <Upload className="size-6 text-accent" aria-hidden />
      <p className="font-serif text-[32px] leading-tight">Drop to import</p>
    </div>
  );
}
