import { Component } from "react";
import type { ErrorInfo, ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  error: { message: string } | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: unknown): State {
    return {
      error: { message: error instanceof Error ? error.message : String(error) },
    };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.error("OILTRACE-AI render error:", error, info.componentStack);
  }

  render() {
    if (this.state.error) {
      return (
        <div
          style={{
            display: "flex",
            flexDirection: "column",
            alignItems: "center",
            justifyContent: "center",
            gap: 12,
            width: "100%",
            height: "100%",
            padding: 24,
            boxSizing: "border-box",
            backgroundColor: "#030712",
            color: "#e5e7eb",
            fontFamily: "ui-sans-serif, system-ui, sans-serif",
            textAlign: "center",
          }}
        >
          <div style={{ fontSize: 16, fontWeight: 700, color: "#fca5a5" }}>
            OILTRACE-AI hit an unexpected error
          </div>
          <div style={{ fontSize: 13, color: "#9ca3af", maxWidth: 560, overflowWrap: "break-word" }}>
            {this.state.error.message}
          </div>
          <button
            onClick={() => this.setState({ error: null })}
            style={{
              marginTop: 4,
              padding: "8px 18px",
              borderRadius: 8,
              border: "none",
              background: "#0891b2",
              color: "#ffffff",
              fontSize: 13,
              fontWeight: 600,
              cursor: "pointer",
            }}
          >
            Try again
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}