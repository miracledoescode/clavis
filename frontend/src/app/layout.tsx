import type { Metadata } from "next";
import { IBM_Plex_Mono, Spectral } from "next/font/google";

import "./globals.css";
import "../styles/clavis.css";

const spectral = Spectral({
  subsets: ["latin"],
  weight: ["300", "400", "500", "600", "700"],
  style: ["normal", "italic"],
  variable: "--font-spectral",
  display: "swap",
});

const plexMono = IBM_Plex_Mono({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-plex-mono",
  display: "swap",
});

export const metadata: Metadata = {
  title: "Clavis — Authored trading",
  description:
    "Turn your best trading self into software. Clavis is an execution layer for a trader's own authored edge — your logic, encoded once and run with discipline.",
};

export default function RootLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body className={`${spectral.variable} ${plexMono.variable} font-serif antialiased`}>
        {children}
      </body>
    </html>
  );
}
