import ErrorBoundary from "@/components/ErrorBoundary";

export default function AuthLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-screen bg-background flex items-center justify-center px-4 py-12">
      <ErrorBoundary>{children}</ErrorBoundary>
    </div>
  );
}