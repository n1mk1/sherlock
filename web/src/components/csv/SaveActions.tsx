// The CSV header's right side (App Flow §8.2, UI brief §5.6): the unsaved count, Discard and Save
// changes (n). Save sends the buffer as one batch; a newer version makes it "Rebase and save": the
// edits go again on the current version, and cells the newer version also changed are listed to
// keep mine or keep theirs. The toast after a save offers Undo (the step) and, for new rows,
// cleaning them: "Clean them" opens the cleaning plan for those rows (PRD CLEAN-1, CLEAN-8a).
import { useState } from "react";
import { toast } from "sonner";
import { ApiError } from "@/api/client";
import { useSaveEdits, useUndo, type Conflict } from "@/api/csv";
import { useCreatePlan } from "@/api/queries";
import type { Dataset } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { Pill } from "@/components/ui/pill";
import { displayValue } from "@/lib/cells";
import { editKey, pendingCount, toBatch, useEdits } from "@/state/edits";
import { useUi } from "@/state/ui";

export function SaveActions({ dataset }: { dataset: Dataset }) {
  const buffer = useEdits((s) => s.buffers[dataset.id]);
  const { discard, rebase } = useEdits();
  const save = useSaveEdits(dataset.id);
  const undo = useUndo(dataset.id);
  const plan = useCreatePlan(dataset.id);
  const setRightOpen = useUi((s) => s.setRightOpen);
  const [confirmDiscard, setConfirmDiscard] = useState(false);
  const [conflicts, setConflicts] = useState<{ list: Conflict[]; current: number } | null>(null);
  const n = pendingCount(buffer);
  const stale = !!buffer && n > 0 && buffer.base !== dataset.current_version;

  const send = async (base: number) => {
    const current = useEdits.getState().buffers[dataset.id]; // fresh: a rebase may just have dropped edits
    if (!current) return;
    const count = pendingCount(current);
    try {
      const res = await save.mutateAsync(toBatch(current, base));
      discard(dataset.id);
      const added = Object.values(res.new_row_ids);
      toast(`Saved ${count} ${count === 1 ? "change" : "changes"}`, {
        duration: 10_000,
        action: {
          label: "Undo",
          onClick: () => undo.mutate({ stepId: res.step.id, base: res.version, confirm: true }, {
            onSuccess: (r) => "version" in r && toast("Undone: back to how it was."),
            onError: (e) => toast.error((e as Error).message),
          }),
        },
      });
      if (added.length) {
        toast(`Run cleaning on the ${added.length} new ${added.length === 1 ? "row" : "rows"}?`, {
          duration: 15_000,
          action: { label: "Clean them", onClick: () => {
            setRightOpen(true); // on a narrow window the right panel is a slide-over
            plan.mutate({ scope: { kind: "new_rows", row_ids: added } }, { onError: (e) => toast.error((e as Error).message) });
          } },
        });
      }
    } catch (e) {
      const err = e as ApiError;
      if (err.status === 409 && typeof err.extra.current_version === "number") {
        const list = (err.extra.conflicts as Conflict[] | undefined) ?? [];
        if (list.length === 0) {
          rebase(dataset.id, err.extra.current_version, []);
          return send(err.extra.current_version); // nothing overlaps: the edits apply as they are
        }
        setConflicts({ list, current: err.extra.current_version });
        return;
      }
      toast.error(err.message);
    }
  };

  if (n === 0) return null;
  return (
    <>
      <Pill tone="accent">{n} unsaved</Pill>
      <Button size="sm" variant="ghost" onClick={() => setConfirmDiscard(true)}>Discard</Button>
      <Button size="sm" variant="primary" loading={save.isPending} onClick={() => send(buffer!.base)}>
        {stale ? "Rebase and save" : `Save changes (${n})`}
      </Button>
      <Dialog open={confirmDiscard} onOpenChange={setConfirmDiscard}>
        <DialogContent className="max-w-[420px] gap-4 p-6">
          <DialogTitle className="type-title">Discard {n} unsaved {n === 1 ? "change" : "changes"}?</DialogTitle>
          <DialogDescription className="text-[14px] text-muted-foreground">They were never saved, so this can't be undone.</DialogDescription>
          <div className="flex justify-end gap-2">
            <Button variant="ghost" onClick={() => setConfirmDiscard(false)}>Cancel</Button>
            <Button variant="primary" onClick={() => { discard(dataset.id); setConfirmDiscard(false); }}>Discard</Button>
          </div>
        </DialogContent>
      </Dialog>
      {conflicts && (
        <ConflictDialog
          list={conflicts.list}
          version={conflicts.current}
          onCancel={() => setConflicts(null)}
          onResolve={(theirs) => {
            rebase(dataset.id, conflicts.current, theirs.map((c) => editKey(c.row_id, c.column)));
            setConflicts(null);
            send(conflicts.current);
          }}
        />
      )}
    </>
  );
}

function ConflictDialog({ list, onCancel, onResolve }: {
  list: Conflict[]; version: number; onCancel: () => void; onResolve: (keepTheirs: Conflict[]) => void;
}) {
  const [theirs, setTheirs] = useState<Set<number>>(new Set());
  return (
    <Dialog open onOpenChange={(o) => !o && onCancel()}>
      <DialogContent className="max-w-[560px] gap-4 p-6">
        <DialogTitle className="type-title">The data changed while you edited</DialogTitle>
        <DialogDescription className="text-[14px] text-muted-foreground">
          A newer change also touched {list.length === 1 ? "a cell" : `${list.length} cells`} you edited. Choose which value to keep;
          the rest of your edits go on top.
        </DialogDescription>
        <div className="max-h-[320px] overflow-y-auto rounded-xl border border-border">
          <table className="w-full text-[13px]">
            <thead className="bg-muted text-left text-muted-foreground">
              <tr><th className="px-3 py-1.5 font-medium">Cell</th><th className="px-3 py-1.5 font-medium">Yours</th>
                <th className="px-3 py-1.5 font-medium">Theirs</th><th className="px-3 py-1.5 font-medium">Keep</th></tr>
            </thead>
            <tbody>
              {list.map((c, i) => (
                <tr key={i} className="border-t border-border">
                  <td className="px-3 py-1.5 font-mono">Row {c.row_id} · {c.column}</td>
                  <td className="px-3 py-1.5 font-mono">{displayValue(c.mine) || "—"}</td>
                  <td className="px-3 py-1.5 font-mono">{displayValue(c.theirs) || "—"}</td>
                  <td className="px-3 py-1.5">
                    <select
                      aria-label={`Keep for row ${c.row_id} ${c.column}`}
                      value={theirs.has(i) ? "theirs" : "mine"}
                      onChange={(e) => setTheirs((s) => { const n = new Set(s); if (e.target.value === "theirs") n.add(i); else n.delete(i); return n; })}
                      className="h-7 rounded-md border border-input bg-card px-1.5"
                    >
                      <option value="mine">Mine</option>
                      <option value="theirs">Theirs</option>
                    </select>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onCancel}>Cancel</Button>
          <Button variant="primary" onClick={() => onResolve(list.filter((_, i) => theirs.has(i)))}>Rebase and save</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
