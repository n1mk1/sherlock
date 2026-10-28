// The offer's choices (App Flow §4): Clean with AI opens the cleaning plan, where nothing changes until
// Start; Clean it myself makes the dataset ready as it is and opens the grid, to edit by hand or ask the
// chat. "Remember my choice" writes the After upload setting, and with Clean with AI the Cleaning depth.
import { Sparkles } from "lucide-react";
import { useState } from "react";
import { toast } from "sonner";
import { useCreatePlan, useSaveSettings, useUseAsIs } from "@/api/queries";
import type { Dataset, Depth } from "@/api/types";
import { Button } from "@/components/ui/button";

export function OfferActions({ dataset, depth = 5 }: { dataset: Dataset; depth?: Depth }) {
  const plan = useCreatePlan(dataset.id);
  const asIs = useUseAsIs(dataset.id);
  const save = useSaveSettings();
  const [remember, setRemember] = useState(false);
  const fail = (err: unknown) => toast.error((err as Error).message);
  const go = (choice: "always" | "never", run: () => void) => {
    if (remember) save.mutate(choice === "always" ? { after_upload: choice, clean_depth: depth } : { after_upload: choice });
    run();
  };
  // After a failed run the labels say what each choice means now (App Flow §5).
  const failed = !!dataset.error;
  return (
    <div className="mt-6 flex flex-col gap-4">
      {failed && (
        <p role="alert" className="rounded-xl bg-red-soft px-3.5 py-2.5 text-[13px] text-red-ink">
          {dataset.error}. Your data is safe: use it as is, or try again.
        </p>
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button variant="ai" loading={plan.isPending} disabled={asIs.isPending}
          onClick={() => go("always", () => plan.mutate({ depth }, { onError: fail }))}>
          {!plan.isPending && <Sparkles aria-hidden />}
          {failed ? "Try cleaning again" : "Clean with AI"}
        </Button>
        <Button loading={asIs.isPending} disabled={plan.isPending}
          // mutateAsync, not mutate's callbacks: the status event can swap this screen for the grid before
          // the answer arrives, and an unmounted component's callbacks don't run.
          onClick={() => go("never", () => { asIs.mutateAsync().catch(fail); })}>
          {failed ? "Use as is" : "Clean it myself"}
        </Button>
        <label className="ml-auto flex items-center gap-2 text-[13px] text-muted-foreground" title="You can change this in Settings">
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} />
          Remember my choice
        </label>
      </div>
    </div>
  );
}
