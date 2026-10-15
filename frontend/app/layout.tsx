import type { Metadata } from "next";
import "./globals.css";
import { Providers } from "@/components/providers";
import { PageShell } from "@/components/page-shell";

export const metadata: Metadata = {
  title: process.env.NEXT_PUBLIC_APP_NAME ?? "Travel Scout",
  description: "Trips built around what you love.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className="min-h-screen text-white antialiased">
        <Providers>
          <PageShell>{children}</PageShell>
        </Providers>
      </body>
    </html>
  );
}
