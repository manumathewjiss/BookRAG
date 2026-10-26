import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";
import { isSupabaseConfigured, safeNextPath, supabaseAnonKey, supabaseUrl } from "@/lib/config";

const PROTECTED = ["/library", "/chat"];
const AUTH_PAGES = ["/login", "/signup"];

export async function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;
  const needsAuth = PROTECTED.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));
  const isAuthPage = AUTH_PAGES.some((prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`));

  if (!isSupabaseConfigured()) {
    return NextResponse.next();
  }

  let response = NextResponse.next({ request });
  const supabase = createServerClient(supabaseUrl(), supabaseAnonKey(), {
    cookies: {
      getAll() {
        return request.cookies.getAll();
      },
      setAll(cookiesToSet) {
        cookiesToSet.forEach(({ name, value }) => request.cookies.set(name, value));
        response = NextResponse.next({ request });
        cookiesToSet.forEach(({ name, value, options }) => response.cookies.set(name, value, options));
      },
    },
  });
  const { data } = await supabase.auth.getUser();

  if (needsAuth && !data.user) {
    const login = request.nextUrl.clone();
    login.pathname = "/login";
    login.searchParams.set("next", pathname);
    return NextResponse.redirect(login);
  }

  if (isAuthPage && data.user) {
    const dest = request.nextUrl.clone();
    dest.pathname = safeNextPath(request.nextUrl.searchParams.get("next"));
    dest.search = "";
    return NextResponse.redirect(dest);
  }

  return response;
}

export const config = {
  matcher: ["/library", "/library/:path*", "/chat", "/chat/:path*", "/login", "/signup"],
};
