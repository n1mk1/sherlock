// The whole-page screen when `GET /me` fails, so a first visit never lands in a shell where every request
// fails too (App Flow §18). The new-visitor cap (TRD §15) gets its own heading and the server's message.
import { AlertCircle } from "lucide-react";
import { ApiError } from "@/api/client";
import { Button } from "@/components/ui/button";

export function StartupError({ error, retrying, onRetry }: { error: unknown; retrying: boolean; onRetry: () => void }) {
  const limited = error instanceof ApiError && error.status === 429;
  const message = error instanceof ApiError ? error.message : "Sherlock couldn't reach its server. Check your connection.";
  return (
    <main className="flex min-h-screen items-center justify-center bg-background p-8 text-foreground">
      <div className="flex max-w-[400px] flex-col items-center gap-4 text-center" role="alert">
        <span className="inline-flex size-12 items-center justify-center rounded-full bg-red-soft" aria-hidden><AlertCircle className="size-5 text-red" /></span>
        <h1 className="type-title">{limited ? "Sherlock can't open a new workspace yet" : "Sherlock couldn't start"}</h1>
        <p className="text-muted-foreground">{message}</p>
        {limited && (
          <p className="text-[12px] text-muted-foreground">A browser that has opened Sherlock before isn't affected.</p>
        )}
        <Button variant="primary" onClick={onRetry} disabled={retrying}>Try again</Button>
      </div>
    </main>
  );
}
