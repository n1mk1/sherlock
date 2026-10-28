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
      <div role="alert" className="m-auto flex max-w-[440px] flex-col gap-3 p-8">
        <h2 className="type-title">Something went wrong showing the {this.props.label}</h2>
        <p className="text-[14px] text-muted-foreground">
          Your data is safe. Try again, or reload if it keeps happening.
        </p>
        <details className="text-[12px] text-muted-foreground"><summary className="cursor-pointer hover:text-foreground">Details</summary><p className="mt-1.5 type-data text-[12px]">{this.state.error.message.slice(0, 300)}</p></details>
        <div className="flex gap-2">
          <Button variant="primary" onClick={() => this.setState({ error: null })}>Try again</Button>
          <Button variant="ghost" onClick={() => window.location.reload()}>Reload</Button>
        </div>
      </div>
    );
  }
}
