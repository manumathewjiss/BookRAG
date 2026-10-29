import type { Metadata } from "next";
import { Source_Sans_3, Source_Serif_4 } from "next/font/google";
import { AuthProvider } from "@/lib/auth/AuthProvider";
import { MockBanner } from "@/components/MockBanner";
import "./globals.css";

const sans = Source_Sans_3({
  subsets: ["latin"],
  weight: ["400", "500", "600"],
  variable: "--font-sans",
});

const serif = Source_Serif_4({
  subsets: ["latin"],
  weight: ["500", "600", "700"],
  variable: "--font-serif",
});

export const metadata: Metadata = {
  title: "BookRAG",
  description: "Private multiuser PDF library and grounded RAG chat.",
};

export const viewport = {
  width: "device-width",
  initialScale: 1,
  viewportFit: "cover" as const,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${sans.variable} ${serif.variable}`}>
      <body>
        <a className="skip-link" href="#main">
          Skip to content
        </a>
        <AuthProvider>
          <MockBanner />
          <div id="main">{children}</div>
        </AuthProvider>
      </body>
    </html>
  );
}
