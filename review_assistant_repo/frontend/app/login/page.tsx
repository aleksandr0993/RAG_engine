"use client";

import { useState } from "react";
import { createClient } from "@supabase/supabase-js";

export default function LoginPage() {
  const [email, setEmail] = useState("");
  const [msg, setMsg] = useState("");

  const url = process.env.NEXT_PUBLIC_SUPABASE_URL || "";
  const anon = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY || "";

  async function magicLink(e: React.FormEvent) {
    e.preventDefault();
    if (!url || !anon) {
      setMsg("Set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_ANON_KEY in .env.local");
      return;
    }
    const supabase = createClient(url, anon);
    const { error } = await supabase.auth.signInWithOtp({ email, options: { emailRedirectTo: window.location.origin } });
    setMsg(error ? error.message : "Check your email for the magic link.");
  }

  return (
    <div>
      <h1>Login (Supabase)</h1>
      <p>Magic link flow; tokens are sent to the API as Bearer for protected writes when enabled.</p>
      <form onSubmit={magicLink}>
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="email" required />
        <button type="submit">Send link</button>
      </form>
      <p>{msg}</p>
    </div>
  );
}
