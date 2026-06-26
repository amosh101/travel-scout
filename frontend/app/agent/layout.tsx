export default function AgentLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="container py-12">
      <h1 className="text-2xl font-semibold">Agent queue</h1>
      <div className="mt-6">{children}</div>
    </div>
  );
}