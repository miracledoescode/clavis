import { createClient } from "@supabase/supabase-js";

// Browser client uses the Supabase ANON key only — RLS scopes every row to the
// authenticated user. Service-role keys never touch the frontend.
const supabaseUrl = process.env.NEXT_PUBLIC_SUPABASE_URL ?? "";
const supabaseAnonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

export const supabase = createClient(supabaseUrl, supabaseAnonKey);
