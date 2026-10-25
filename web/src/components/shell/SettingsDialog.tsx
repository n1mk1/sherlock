// Settings (UI brief §5.11, App Flow §13). Cut 1 keeps four settings: mode, accent, chat bar and
// after upload. Changes apply at once and save to the profile; the mode and accent preview live.
import type { ReactNode } from "react";
import { useSearchParams } from "react-router-dom";
import { useMe, useSaveSettings } from "@/api/queries";
import type { Settings } from "@/api/types";
import { Button } from "@/components/ui/button";
import { Dialog, DialogClose, DialogContent, DialogTitle } from "@/components/ui/dialog";
import { Segmented } from "@/components/ui/segmented";

const ACCENTS: { value: Settings["accent"]; label: string; light: string; dark: string }[] = [
  { value: "verdigris", label: "Verdigris", light: "#2F6B62", dark: "#6FB3A6" },
  { value: "arcane", label: "Arcane", light: "#6A4C93", dark: "#A88BD6" },
  { value: "ember", label: "Ember", light: "#9A4A2E", dark: "#E08A62" },
  { value: "aether", label: "Aether", light: "#2F6690", dark: "#6FB4D9" },
  { value: "brass", label: "Brass", light: "#8A5A33", dark: "#C9A063" },
];

export function useSettingsOpen() {
  const [params, setParams] = useSearchParams();
  const open = params.get("settings") === "1";
  const setOpen = (next: boolean) => {
    const p = new URLSearchParams(params);
    if (next) p.set("settings", "1");
    else p.delete("settings");
    setParams(p, { replace: true });
  };
  return [open, setOpen] as const;
}

export function SettingsDialog() {
  const [open, setOpen] = useSettingsOpen();
  const { data: me } = useMe();
  const save = useSaveSettings();
  const s = me?.settings;
  const set = (patch: Partial<Settings>) => save.mutate(patch);
  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogContent className="max-w-[580px]" aria-describedby={undefined}>
        <div className="px-6 pb-2 pt-5">
          <DialogTitle className="font-serif text-[32px] leading-tight">Settings</DialogTitle>
        </div>
        {s && (
          <div className="flex min-h-0 flex-1 flex-col gap-5 overflow-y-auto px-6 py-4">
            <Field label="Mode" help="System follows your computer's light or dark setting.">
              <Segmented label="Mode" value={s.theme} onChange={(theme) => set({ theme })}
                options={[{ value: "light", label: "Light" }, { value: "dark", label: "Dark" }, { value: "system", label: "System" }]} />
            </Field>
            <Field label="Accent" help="The one color that marks what you're looking at.">
              <Segmented label="Accent" value={s.accent} onChange={(accent) => set({ accent })}
                options={ACCENTS.map((a) => ({
                  value: a.value,
                  label: (
                    <>
                      <span aria-hidden className="size-2.5 rounded-full dark:hidden" style={{ background: a.light }} />
                      <span aria-hidden className="hidden size-2.5 rounded-full dark:inline-block" style={{ background: a.dark }} />
                      {a.label}
                    </>
                  ),
                }))} />
            </Field>
            <Field label="Chat bar" help="Auto-hide shows the bar when you point at it or tab to it.">
              <Segmented label="Chat bar" value={s.chatbar} onChange={(chatbar) => set({ chatbar })}
                options={[{ value: "pinned", label: "Pinned" }, { value: "autohide", label: "Auto-hide" }, { value: "hidden", label: "Hidden" }]} />
            </Field>
            <Field label="After upload" help="What happens once a new CSV is profiled.">
              <Segmented label="After upload" value={s.after_upload} onChange={(after_upload) => set({ after_upload })}
                options={[{ value: "ask", label: "Ask me" }, { value: "always", label: "Always clean" }, { value: "never", label: "Never clean" }]} />
            </Field>
          </div>
        )}
        <div className="flex items-center gap-3 border-t border-border px-6 py-4">
          <span className="mr-auto text-[13px] text-muted-foreground">Saved to your Sherlock profile</span>
          <DialogClose asChild>
            <Button variant="primary">Done</Button>
          </DialogClose>
        </div>
      </DialogContent>
    </Dialog>
  );
}

function Field({ label, help, children }: { label: string; help: string; children: ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <span className="text-[13px] font-semibold">{label}</span>
      {children}
      <span className="text-[13px] text-muted-foreground">{help}</span>
    </div>
  );
}
