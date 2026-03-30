import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Travel Scout - Find Your Perfect Flight",
  description: "Get notified when flight deals match your travel interests",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-screen">{children}</body>
    </html>
  );
}