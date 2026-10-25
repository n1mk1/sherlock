// Error boundaries (Implementation Plan D8.3): a crash in one view shows a calm message there with Try
// again, instead of blanking the whole app. The data is on the server, so nothing is lost.
import { Component, type ErrorInfo, type ReactNode } from "react";
import { Button } from "@/components/ui/button";

export class ErrorBoundary extends Component<{ children: ReactNode; label: string; resetKey?: string }, { error: Error | null }> {
  state: { error: Error | null } = { error: null };

  static getDerivedStateFromError(error: Error) {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error(`[${this.props.label}]`, error, info.componentStack);
  }

  componentDidUpdate(prev: { resetKey?: string }) {
    // Moving to another dataset or tab starts that view afresh.
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null });
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <div role="alert" className="m-6 flex max-w-[520px] flex-col gap-3 rounded-[16px] border border-border bg-card p-5">
        <h2 className="text-[15px] font-semibold">Something went wrong showing the {this.props.label}</h2>
        <p className="text-[14px] text-muted-foreground">
          Your data is safe on the server. Try again, or reload the page if it keeps happening.
        </p>
        <p className="font-mono text-[12px] text-muted-foreground">{this.state.error.message.slice(0, 300)}</p>
        <div className="flex gap-2">
          <Button size="sm" variant="primary" onClick={() => this.setState({ error: null })}>Try again</Button>
          <Button size="sm" variant="ghost" onClick={() => window.location.reload()}>Reload</Button>
        </div>
      </div>
    );
  }
}
