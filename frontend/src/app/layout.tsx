import type { Metadata } from "next";
import localFont from "next/font/local";

import { Providers } from "./providers";
import "./globals.css";

// Fonts are self-hosted from the Fontsource packages (OFL-1.1), so builds need no network.
// next/font requires these options to be literal values.
// Public Sans (interface, tables, figures: it has tabular digits) and Source Serif 4 (headings
// and written answers).
const publicSans = localFont({
  src: "../../node_modules/@fontsource-variable/public-sans/files/public-sans-latin-wght-normal.woff2",
  weight: "100 900",
  variable: "--font-public-sans",
  display: "swap",
});

const sourceSerif = localFont({
  src: "../../node_modules/@fontsource-variable/source-serif-4/files/source-serif-4-latin-wght-normal.woff2",
  weight: "200 900",
  variable: "--font-source-serif",
  display: "swap",
});

export const metadata: Metadata = {
  title: {
    default: "Autonomous Data Analyst",
    template: "%s | Autonomous Data Analyst",
  },
  description:
    "Upload a spreadsheet, check its profile, and ask questions. Every figure in an answer is checked against a computation you can open.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    // data-theme is set by theme-init.js before React hydrates, so the server's <html> can differ.
    <html
      lang="en"
      className={`${publicSans.variable} ${sourceSerif.variable}`}
      suppressHydrationWarning
    >
      <head>
        {/* Must block rendering: it applies the saved theme before the first paint. */}
        {/* eslint-disable-next-line @next/next/no-sync-scripts */}
        <script src="/theme-init.js" />
      </head>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
