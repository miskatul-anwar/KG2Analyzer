import { Component, type ErrorInfo, type ReactNode } from "react";

/** Keeps one broken widget from blanking the whole app; offers a retry instead. */
export class ErrorBoundary extends Component<{ children: ReactNode; quiet?: boolean }, { error: Error | null }> {
  state = { error: null as Error | null };
  static getDerivedStateFromError(error: Error) { return { error }; }
  componentDidCatch(error: Error, info: ErrorInfo) { console.error("UI error:", error, info.componentStack); }
  render() {
    if (!this.state.error) return this.props.children;
    if (this.props.quiet) return null;
    return (
      <div className="mx-auto mt-10 max-w-lg rounded-xl border border-bad/40 bg-card p-6 text-center">
        <div className="font-semibold text-bad">Something went wrong on this page.</div>
        <p className="mt-1 text-sm text-ink-2">{this.state.error.message}</p>
        <button className="btn mt-4" onClick={() => this.setState({ error: null })}>Try again</button>
      </div>
    );
  }
}
