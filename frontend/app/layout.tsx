import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FeelIQ Department Timetable Archive",
  description: "Store, review, verify, publish, and search department timetable PDFs with FeelIQ Technologies.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
