"use client";
import { useState } from "react";
import type { ApiError, ApiResult } from "@/lib/api";
import { UNREACHABLE } from "@/lib/apiErrors";

export type Note = { kind: "ok" | "problem"; text: string } | null;

/** Run one write step: busy while it runs, then an ok/problem note, then `after` (e.g. reload) on success. */
export function useStep(problem: (status: number, error: ApiError) => string, after?: () => unknown) {
  const [busy, setBusy] = useState(false);
  const [note, setNote] = useState<Note>(null);

  async function run(call: () => Promise<ApiResult<unknown>>, success: string): Promise<boolean> {
    setBusy(true);
    setNote(null);
    try {
      const r = await call();
      const ok = r.status >= 200 && r.status < 300;
      setNote(ok ? { kind: "ok", text: success } : { kind: "problem", text: problem(r.status, r.error) });
      if (ok && after) await after();
      return ok;
    } catch {
      setNote({ kind: "problem", text: UNREACHABLE });
      return false;
    } finally {
      setBusy(false);
    }
  }

  return { busy, note, run };
}
