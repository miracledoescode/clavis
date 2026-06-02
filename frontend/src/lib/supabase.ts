import { createClient } from "@supabase/supabase-js";

// Browser client uses the Supabase ANON key only — RLS scopes every row to the
// authenticated user. Service-role keys never touch the frontend.
// Real values are baked in at build time from NEXT_PUBLIC_* (e.g. on Vercel).
// The localhost fallbacks only keep `createClient` from throwing during a build
// with no env set; the app needs the real values at runtime.
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL || "http://localhost:54321";
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "anon-key-placeholder";

export const supabase = createClient(supabaseUrl, supabaseAnonKey);
