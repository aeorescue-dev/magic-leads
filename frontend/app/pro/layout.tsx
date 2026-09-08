export default function ProLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <div className="min-h-screen antialiased">{children}</div>;
}
