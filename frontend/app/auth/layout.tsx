import Link from "next/link";

/**
 * Auth shell layout. The full forms (login, register, password reset) land in
 * the user-journey card; this minimal layout proves routing works.
 */
export default function AuthLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex min-h-screen flex-col">
      <header className="border-b border-border">
        <div className="container flex h-14 items-center">
          <Link href="/" className="font-semibold">
            Travel Scout
          </Link>
        </div>
      </header>
      <main className="container flex flex-1 items-center justify-center py-12">
        {children}
      </main>
    </div>
  );
}