"use client";

import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  hasError: boolean;
}

export default class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: unknown) {
    console.error("ErrorBoundary capturou erro:", error);
  }

  handleReload = () => {
    window.location.reload();
  };

  render() {
    if (this.state.hasError) {
      return (
        <div className="min-h-[60vh] flex items-center justify-center p-6">
          <div className="max-w-sm w-full text-center rounded-2xl border border-white/10 bg-white/5 p-8">
            <div className="h-14 w-14 mx-auto rounded-2xl bg-rose-500/15 flex items-center justify-center text-rose-500 font-bold text-lg">!</div>
            <h2 className="text-lg font-bold text-slate-100">Algo deu errado</h2>
            <p className="text-sm text-slate-400 mt-2">
              Ocorreu um erro inesperado ao carregar esta página. Recarregue para tentar novamente.
            </p>
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
