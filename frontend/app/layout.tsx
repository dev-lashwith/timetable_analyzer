import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "FeelIQ Timetable Extractor",
  description: "Turn a timetable image into an editable spreadsheet with FeelIQ Technologies.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
