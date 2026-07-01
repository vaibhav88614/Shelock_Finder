import React from "react";

interface State {
  error: Error | null;
}

/**
 * Root-level error boundary. Without this, any uncaught render-time error
 * unmounts the whole app to a blank page. With it, the user gets a visible
 * fallback and a reload button, and the error is logged to the console.
 */
export class ErrorBoundary extends React.Component<
  React.PropsWithChildren,
  State
> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: React.ErrorInfo): void {
    // No external telemetry — JobPulse is offline-by-design. DevTools is the
    // intended destination.
    console.error("ErrorBoundary caught:", error, info);
  }

  render(): React.ReactNode {
    const err = this.state.error;
    if (err) {
      return (
        <div className="min-h-screen flex items-center justify-center bg-slate-50 p-6">
          <div className="max-w-md bg-white border border-red-200 rounded-lg shadow p-6 text-sm">
            <h1 className="text-base font-semibold text-red-800 mb-2">
              Something went wrong
            </h1>
            <p className="text-slate-700 mb-3">
              The dashboard hit an unexpected error and may not be usable until
              you reload. Open DevTools console for the full stack.
            </p>
            <pre className="text-xs bg-slate-50 border border-slate-200 rounded p-2 mb-3 overflow-x-auto whitespace-pre-wrap">
              {err.message}
            </pre>
            <button
              type="button"
              onClick={() => window.location.reload()}
              className="text-sm bg-slate-900 text-white rounded px-3 py-1.5 hover:bg-slate-700"
            >
              Reload page
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
