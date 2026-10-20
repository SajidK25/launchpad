import { Component, type ReactNode } from "react";

type AppErrorBoundaryProps = {
  children: ReactNode;
};

type AppErrorBoundaryState = {
  hasError: boolean;
};

export class AppErrorBoundary extends Component<
  AppErrorBoundaryProps,
  AppErrorBoundaryState
> {
  state: AppErrorBoundaryState = { hasError: false };

  static getDerivedStateFromError(): AppErrorBoundaryState {
    return { hasError: true };
  }

  render() {
    if (this.state.hasError) {
      return (
        <main className="ui-error-page">
          <section className="ui-error-panel" aria-labelledby="ui-error-title">
            <p className="ui-eyebrow">LAUNCHPAD</p>
            <h1 id="ui-error-title">This page hit a snag</h1>
            <p>
              We couldn’t show this page. You can reload it or return to the
              Launchpad home page.
            </p>
            <div className="ui-error-actions">
              <button type="button" onClick={() => window.location.reload()}>
                Reload page
              </button>
              <a href="/">Go to Launchpad home</a>
            </div>
          </section>
        </main>
      );
    }

    return this.props.children;
  }
}
