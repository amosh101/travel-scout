import Link from "next/link";

/**
 * Public landing page. Foundation card scope: clean placeholder landing that
 * proves the theme + providers + Tailwind tokens render. User/admin journeys
 * land in t3_user_journey and t4_admin_journey.
 */
export default function HomePage() {
  return (
    <main className="container flex flex-col items-center justify-center gap-12 py-24">
      <h1 className="text-4xl font-semibold tracking-tight sm:text-5xl">
        Travel Scout
      </h1>
      <p className="max-w-prose text-center text-muted-foreground">
        Travel Scout finds trips at the intersection of your interests — real
        events, real flights, real dates. Set your interests, and the app does
        the cross-referencing.
      </p>

      <nav className="flex flex-wrap items-center justify-center gap-4">
        <Link
          href="/auth/login"
          className="rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground hover:opacity-90"
        >
          Sign in
        </Link>
        <Link
          href="/auth/register"
          className="rounded-md border border-border px-4 py-2 text-sm font-medium hover:bg-accent"
        >
          Create account
        </Link>
      </nav>

      <div className="mt-16 grid w-full max-w-3xl gap-6 sm:grid-cols-3">
        <Feature title="Interests" body="F1, jazz, renaissance art — pick what you love." />
        <Feature title="Intersections" body="Where your interests and real dates overlap." />
        <Feature title="Save trips" body="Get notified when the math finds a match." />
      </div>
    </main>
  );
}

function Feature({ title, body }: { title: string; body: string }) {
  return (
    <article className="rounded-lg border border-border bg-card p-6">
      <h2 className="text-lg font-semibold">{title}</h2>
      <p className="mt-2 text-sm text-muted-foreground">{body}</p>
    </article>
  );
}