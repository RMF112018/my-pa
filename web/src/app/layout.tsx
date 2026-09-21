import type { Metadata, Viewport } from "next";
import "./globals.css";
import { ServiceWorkerRegister } from "@/components/pwa/sw-register";

export const metadata: Metadata = {
  title: "My PA",
  description: "Evidence-first, principal-scoped personal assistant.",
  manifest: "/manifest.webmanifest",
  icons: {
    icon: [
      {
        url: "/icons/favicon-light-32.png",
        type: "image/png",
        sizes: "32x32",
        media: "(prefers-color-scheme: light)",
      },
      {
        url: "/icons/favicon-dark-32.png",
        type: "image/png",
        sizes: "32x32",
        media: "(prefers-color-scheme: dark)",
      },
      {
        url: "/favicon.ico",
        type: "image/x-icon",
        sizes: "any",
      },
    ],
  },
};

export const viewport: Viewport = {
  themeColor: "#173F67",
  // Required for `env(safe-area-inset-*)` to resolve non-zero on iOS. Without
  // it every safe-area rule in this application is inert.
  viewportFit: "cover",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="antialiased">
        <a
          href="#main"
          className="sr-only focus:not-sr-only focus:absolute focus:left-2 focus:top-2 focus:z-50 focus:rounded focus:bg-surface focus:px-3 focus:py-2"
        >
          Skip to main content
        </a>
        {children}
        <ServiceWorkerRegister />
      </body>
    </html>
  );
}
