"use client";

import { Component, type ErrorInfo, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
  error: unknown;
}

declare global {
  interface Window {
    __GARIMPADOR_LAST_ERROR__?: {
      message: string;
      stack: string;
      componentStack: string;
      at: string;
    };
  }
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, error: null };

  static getDerivedStateFromError(error: unknown): State {
    return { hasError: true, error };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    const message = error instanceof Error ? error.message : String(error);
    const stack = error instanceof Error ? error.stack || "" : "";
    const componentStack = info?.componentStack || "";
    // Diagnóstico: expõe message + stack completos para debug no iOS.
    console.error("[ErrorBoundary] message:", message);
    console.error("[ErrorBoundary] stack:", stack);
    console.error("[ErrorBoundary] componentStack:", componentStack);
    try {
      const detail = { message, stack, componentStack, at: new Date().toISOString() };
      window.__GARIMPADOR_LAST_ERROR__ = detail;
      try {
        window.localStorage.setItem("garimpador.last_error", JSON.stringify(detail));
      } catch {
        /* storage indisponível */
      }
    } catch {
      /* ignore */
    }
  }

  handleReload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      const message =
        this.state.error instanceof Error ? this.state.error.message : String(this.state.error);
      return (
        <div className="min-h-[60vh] flex items-center justify-center p-6">
          <div className="max-w-sm w-full text-center rounded-2xl border border-white/10 bg-white/5 p-8">
            <div className="h-14 w-14 mx-auto rounded-2xl bg-rose-500/15 flex items-center justify-center text-rose-500 font-bold text-lg">!</div>
            <h2 className="text-lg font-bold text-slate-100">Algo deu errado</h2>
            <p className="text-sm text-slate-400 mt-2">
              Ocorreu um erro inesperado ao carregar esta página. Recarregue para tentar novamente.
            </p>
            {message && message !== "undefined" && (
              <p className="mt-3 text-xs text-rose-300/90 break-words border border-rose-500/20 bg-rose-500/10 rounded-lg px-3 py-2">
                {message}
              </p>
            )}
            <button
              onClick={this.handleReload}
              className="mt-5 px-5 py-2.5 rounded-xl bg-indigo-500 hover:bg-indigo-400 text-white font-semibold transition"
            >
              Recarregar página
            </button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
