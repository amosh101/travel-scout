import { redirect } from "next/navigation";

/**
 * Admin layout. Real auth + role guard lands in t4_admin_journey; for the
 * foundation card we render the shell and a stub.
 *
 * NOTE: the API layer enforces Tailscale CIDR gating independently
 * (TailscaleAdminGate middleware in the backend), so even un-guarded
 * rendering here is safe.
 */
export default function AdminLayout({ children }: { children: React.ReactNode }) {
  // Real auth check happens in t4; foundation card keeps the route discoverable.
  return (
    <div className="flex min-h-screen">
      <aside className="w-60 border-r border-border bg-card p-6">
        <h2 className="text-lg font-semibold">Admin</h2>
        <nav className="mt-4 space-y-2 text-sm">
          <a href="/admin" className="block hover:underline">
            Overview
          </a>
          <a href="/admin/audit" className="block hover:underline">
            Audit log
          </a>
          <a href="/admin/users" className="block hover:underline">
            Users
          </a>
        </nav>
      </aside>
      <main className="flex-1 p-8">{children}</main>
    </div>
  );
}