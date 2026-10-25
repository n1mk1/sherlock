// The offer's choices (App Flow §4): Clean it for me, Use as is, (P1) Go step by step, and
// "Remember my choice", which writes the After upload setting.
import { useState } from "react";
import { toast } from "sonner";
import { useSaveSettings, useStartCleaning, useUseAsIs } from "@/api/queries";
import type { Dataset } from "@/api/types";
import { Button } from "@/components/ui/button";

export function OfferActions({ dataset }: { dataset: Dataset }) {
  const clean = useStartCleaning(dataset.id);
  const asIs = useUseAsIs(dataset.id);
  const save = useSaveSettings();
  const [remember, setRemember] = useState(false);
  const fail = (err: unknown) => toast.error((err as Error).message);
  const go = (choice: "always" | "never", run: () => void) => {
    if (remember) save.mutate({ after_upload: choice });
    run();
  };
  return (
    <div className="mt-6 flex flex-col gap-4">
      {dataset.error && (
        <p role="alert" className="text-[13px] text-destructive">
          {dataset.error}. Your data is safe; you can build the dashboard without cleaning or try again.
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" loading={clean.isPending} disabled={asIs.isPending}
          onClick={() => go("always", () => clean.mutate(undefined, { onError: fail }))}>
          {dataset.error ? "Try cleaning again" : "Clean it for me"}
        </Button>
        <Button loading={asIs.isPending} disabled={clean.isPending}
          onClick={() => go("never", () => asIs.mutate(undefined, { onError: fail }))}>
          {dataset.error ? "Build dashboard without cleaning" : "Use as is"}
        </Button>
        <Button disabled title="Step-by-step cleaning comes in a later release">Go step by step</Button>
      </div>
      <label className="flex items-center gap-2 text-[13px] text-muted-foreground">
        <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="accent-[var(--accent)]" />
        Remember my choice
      </label>
    </div>
  );
}
