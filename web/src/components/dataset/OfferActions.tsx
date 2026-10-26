// The offer's choices (App Flow §4): Clean with AI opens the cleaning plan, where nothing changes until
// Start; Clean it myself builds the dashboard on the data as it is and opens the CSV tab, to edit by hand
// or ask the chat. "Remember my choice" writes the After upload setting.
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useCreatePlan, useSaveSettings, useUseAsIs } from "@/api/queries";
import type { Dataset } from "@/api/types";
import { Button } from "@/components/ui/button";

export function OfferActions({ dataset }: { dataset: Dataset }) {
  const plan = useCreatePlan(dataset.id);
  const asIs = useUseAsIs(dataset.id);
  const save = useSaveSettings();
  const navigate = useNavigate();
  const [remember, setRemember] = useState(false);
  const fail = (err: unknown) => toast.error((err as Error).message);
  const go = (choice: "always" | "never", run: () => void) => {
    if (remember) save.mutate({ after_upload: choice });
    run();
  };
  // After a failed run the labels say what each choice means now (App Flow §5).
  const failed = !!dataset.error;
  return (
    <div className="mt-6 flex flex-col gap-4">
      {failed && (
        <p role="alert" className="text-[13px] text-destructive">
          {dataset.error}. Your data is safe; you can build the dashboard without cleaning or try again.
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        <Button variant="primary" loading={plan.isPending} disabled={asIs.isPending}
          onClick={() => go("always", () => plan.mutate(undefined, { onError: fail }))}>
          {failed ? "Try cleaning again" : "Clean with AI"}
        </Button>
        <Button loading={asIs.isPending} disabled={plan.isPending}
          // mutateAsync, not mutate's callbacks: the status event can swap this screen for the building
          // screen before the answer arrives, and an unmounted component's callbacks don't run.
          onClick={() => go("never", () => {
            asIs.mutateAsync().then(() => { if (!failed) navigate(`/d/${dataset.id}/csv`); }, fail);
          })}>
          {failed ? "Build dashboard without cleaning" : "Clean it myself"}
        </Button>
      </div>
      <div className="flex flex-wrap items-center gap-x-2 text-[13px] text-muted-foreground">
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} className="accent-[var(--accent)]" />
          Remember my choice
        </label>
        <span className="text-[12px]">· You can change this in Settings</span>
      </div>
    </div>
  );
}
