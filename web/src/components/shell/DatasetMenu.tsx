// The dataset menu (⋯, UI/UX brief §5.14), in the dataset's header: Export notebook, Download CSV, Rename,
// Delete. Delete confirms, then offers Undo for 10 s.
import { BookOpen, Download, MoreHorizontal, Pencil, Trash2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { toast } from "sonner";
import { useDeleteDataset, useRenameDataset, useRestoreDataset } from "@/api/queries";
import type { Dataset } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import { MenuContent, MenuItem, MenuRoot, MenuSeparator, MenuShortcut, MenuTrigger } from "@/components/ui/menu";
import { useUi } from "@/state/ui";
import { exportBlocked } from "./ExportDialog";

export function useDatasetCommands(dataset: Dataset) {
  const rename = useRenameDataset();
  const del = useDeleteDataset();
  const restore = useRestoreDataset();
  const navigate = useNavigate();
  return {
    rename: (name: string) => {
      const clean = name.trim();
      if (!clean || clean === dataset.name) return;
      rename.mutate({ id: dataset.id, name: clean }, { onError: (e) => toast.error((e as Error).message) });
    },
    remove: (leave: boolean) =>
      del.mutate(dataset.id, {
        onSuccess: () => {
          if (leave) navigate("/", { state: { stay: true } });
          toast(`Deleted ${dataset.name}`, {
            duration: 10_000,
            action: { label: "Undo", onClick: () => restore.mutate(dataset.id, { onSuccess: (ds) => leave && navigate(`/d/${ds.id}`) }) },
          });
        },
        onError: (e) => toast.error((e as Error).message),
      }),
    downloadRaw: () => window.location.assign(`/api/v1/datasets/${dataset.id}/raw.csv`),
    downloadCsv: () => window.location.assign(`/api/v1/datasets/${dataset.id}/export.csv`),
  };
}

export function ConfirmDelete({ dataset, open, onOpenChange, onConfirm }: {
  dataset: Dataset; open: boolean; onOpenChange: (o: boolean) => void; onConfirm: () => void;
}) {
  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-[420px] gap-4 p-6">
        <DialogTitle className="type-title">Delete {dataset.name}?</DialogTitle>
        <DialogDescription className="text-[14px] text-muted-foreground">
          Its changes and chat go with it. You can undo for 10 seconds.
        </DialogDescription>
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
          <Button variant="primary" className="bg-red text-primary-foreground" onClick={() => { onOpenChange(false); onConfirm(); }}>Delete</Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}

export function RenameDialog({ dataset, open, onOpenChange, onRename }: {
  dataset: Dataset; open: boolean; onOpenChange: (o: boolean) => void; onRename: (name: string) => void;
}) {
  const [name, setName] = useState(dataset.name);
  return (
    <Dialog open={open} onOpenChange={(o) => { setName(dataset.name); onOpenChange(o); }}>
      <DialogContent className="max-w-[420px] gap-4 p-6">
        <DialogTitle className="type-title">Rename</DialogTitle>
        <DialogDescription className="sr-only">A new name for this CSV</DialogDescription>
        <form
          className="flex flex-col gap-4"
          onSubmit={(e) => { e.preventDefault(); onRename(name); onOpenChange(false); }}
        >
          <input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            aria-label="Name"
            className="h-10 rounded-xl border border-input bg-card px-3.5 text-[14px] outline-none focus-visible:border-accent focus-visible:shadow-[0_0_0_3px_var(--accent-soft)]"
          />
          <div className="flex justify-end gap-2">
            <Button type="button" variant="ghost" onClick={() => onOpenChange(false)}>Cancel</Button>
            <Button type="submit" variant="primary" disabled={!name.trim()}>Rename</Button>
          </div>
        </form>
      </DialogContent>
    </Dialog>
  );
}

export function DatasetMenu({ dataset }: { dataset: Dataset }) {
  const cmd = useDatasetCommands(dataset);
  const [renaming, setRenaming] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const setExportOpen = useUi((s) => s.setExportOpen);
  const blocked = exportBlocked(dataset);
  return (
    <>
      <MenuRoot>
        <MenuTrigger asChild>
          <button
            type="button"
            aria-label="Dataset menu"
            className="inline-flex size-8 items-center justify-center rounded-full text-muted-foreground hover:bg-secondary hover:text-foreground focus-visible:outline-2 focus-visible:outline-ring data-[state=open]:bg-secondary"
          >
            <MoreHorizontal className="size-4" />
          </button>
        </MenuTrigger>
        <MenuContent>
          <MenuItem onSelect={() => setExportOpen(true)} disabled={!!blocked}>
            <BookOpen /> Export notebook<MenuShortcut>{blocked ?? "Ctrl+Shift+E"}</MenuShortcut>
          </MenuItem>
          <MenuItem onSelect={cmd.downloadCsv} disabled={dataset.current_version === 0}><Download /> Download CSV</MenuItem>
          <MenuItem onSelect={() => setRenaming(true)}><Pencil /> Rename</MenuItem>
          <MenuSeparator />
          <MenuItem destructive onSelect={() => setDeleting(true)}><Trash2 /> Delete</MenuItem>
        </MenuContent>
      </MenuRoot>
      <RenameDialog dataset={dataset} open={renaming} onOpenChange={setRenaming} onRename={cmd.rename} />
      <ConfirmDelete dataset={dataset} open={deleting} onOpenChange={setDeleting} onConfirm={() => cmd.remove(true)} />
    </>
  );
}
