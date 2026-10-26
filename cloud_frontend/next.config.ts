import fs from "node:fs";
import path from "node:path";
import type { NextConfig } from "next";

function copyPdfWorker(): void {
  const src = path.join(__dirname, "node_modules/pdfjs-dist/build/pdf.worker.min.mjs");
  const dest = path.join(__dirname, "public/pdf.worker.min.mjs");
  if (!fs.existsSync(src)) return;
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(src, dest);
}

copyPdfWorker();

/** Keep this local: importing src/lib/config from next.config breaks client env inlining. */
function assertPublicBrowserEnv(): void {
  const production = process.env.NODE_ENV === "production" || process.env.VERCEL_ENV === "production";
  const mock = (process.env.NEXT_PUBLIC_BOOKRAG_USE_MOCK || "").trim().toLowerCase();
  const localAuth = (process.env.NEXT_PUBLIC_BOOKRAG_LOCAL_TEST_AUTH || "").trim().toLowerCase();
  const enabled = (raw: string) => raw === "true" || raw === "1" || raw === "on";
  if (production && enabled(mock)) {
    throw new Error("NEXT_PUBLIC_BOOKRAG_USE_MOCK cannot be enabled for a production build.");
  }
  if (production && enabled(localAuth)) {
    throw new Error("NEXT_PUBLIC_BOOKRAG_LOCAL_TEST_AUTH cannot be enabled for a production build.");
  }
  const anon = (process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "").trim();
  if (/service_role|supabase_admin/i.test(anon)) {
    throw new Error("NEXT_PUBLIC_SUPABASE_ANON_KEY must be the anon/public key, not a service-role JWT.");
  }
  for (const [name, value] of Object.entries(process.env)) {
    if (!name.startsWith("NEXT_PUBLIC_")) continue;
    const blob = `${name}=${value || ""}`;
    if (/SERVICE_ROLE|VOYAGE_API_KEY|OPENAI_API_KEY|SUPABASE_SERVICE/i.test(blob)) {
      throw new Error(`${name} must not carry a private backend secret into the browser bundle.`);
    }
  }
}

assertPublicBrowserEnv();

const securityHeaders = [
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];

const nextConfig: NextConfig = {
  reactStrictMode: true,
  poweredByHeader: false,
  transpilePackages: ["pdfjs-dist"],
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
  webpack: (config) => {
    config.cache = false;
    config.resolve.alias = {
      ...config.resolve.alias,
      canvas: false,
    };
    return config;
  },
};

export default nextConfig;
