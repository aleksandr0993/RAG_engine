import type { Metadata } from "next";
import Link from "next/link";
import "./globals.css";

export const metadata: Metadata = {
  title: "Review Assistant",
  description: "Dashboard for review assistant API",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body>
        <nav>
          <Link href="/dashboard">Dashboard</Link>
          <Link href="/projects/upload">Upload</Link>
          <Link href="/catalog">Catalog</Link>
          <Link href="/admin/assignments">Admin assignments</Link>
          <Link href="/login">Login</Link>
        </nav>
        <main>{children}</main>
      </body>
    </html>
  );
}
