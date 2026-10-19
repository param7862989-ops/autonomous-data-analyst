import type { Metadata } from "next";
import localFont from "next/font/local";

import { Providers } from "./providers";
import "./globals.css";

// Fonts are self-hosted from the Fontsource packages (OFL-1.1), so builds need no network.
// next/font requires these options to be literal values.
const plexSans = localFont({
  src: [
    {
      path: "../../node_modules/@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-400-normal.woff2",
      weight: "400",
      style: "normal",
    },
    {
      path: "../../node_modules/@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-500-normal.woff2",
      weight: "500",
      style: "normal",
    },
    {
      path: "../../node_modules/@fontsource/ibm-plex-sans/files/ibm-plex-sans-latin-600-normal.woff2",
      weight: "600",
      style: "normal",
    },
  ],
  variable: "--font-plex-sans",
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
    "Upload a dataset, review its profile, and ask questions answered with computed evidence.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en" className={`${plexSans.variable} ${sourceSerif.variable}`}>
      <body>
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
