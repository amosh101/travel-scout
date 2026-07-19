import { Suspense } from "react";
import SearchClient from "./SearchClient";

export const dynamic = "force-dynamic";

export default function SearchPage() {
  return (
    <main className="container max-w-3xl space-y-6 py-12">
      <h1 className="text-3xl font-semibold">Search results</h1>
      <Suspense
        fallback={
          <div className="py-12 text-center text-muted-foreground">Loading…</div>
        }
      >
        <SearchClient />
      </Suspense>
    </main>
  );
}
