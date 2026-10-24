import { useEffect, useState } from "react";

type Health = { ok: boolean; version: string };

// Scaffold placeholder: the three-panel shell replaces this (Implementation Plan D2.9).
export function App() {
  const [health, setHealth] = useState<Health | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    fetch("/healthz")
      .then((r) => (r.ok ? r.json() : Promise.reject(r.status)))
      .then(setHealth)
      .catch(() => setFailed(true));
  }, []);

  return (
    <main className="mx-auto flex min-h-screen max-w-xl flex-col justify-center gap-2 p-6">
      <h1 className="text-2xl font-semibold">Sherlock</h1>
      <p className="text-muted-foreground" role="status">
        {health ? `API ${health.version} is up` : failed ? "API unreachable" : "Checking the API…"}
      </p>
    </main>
  );
}
