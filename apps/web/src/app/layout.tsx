import "./globals.css";

import type { Metadata, Viewport } from "next";

import { Providers } from "./providers";

export const metadata: Metadata = {
  title: { default: "AEGIS", template: "%s · AEGIS" },
  description: "AEGIS — Advanced Evidence, Generation Intelligence & Synthetic-Media Forensics System",
  robots: { index: false, follow: false },
};

export const viewport: Viewport = { themeColor: "#060a13", colorScheme: "dark" };

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className="dark">
      <body className="min-h-screen font-sans">
        <Providers>{children}</Providers>
      </body>
    </html>
  );
}
