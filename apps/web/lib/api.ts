import "server-only";
import { readFileSync } from "node:fs";
import { createWEClient, type Schemas } from "@we/sdk";

export type { Schemas };

/** Token de desenvolvimento lido no servidor (WE_WEB_TOKEN_FILE). Em produção: sessão OIDC (pendente, ADR-0006). */
function token(): string | null {
  const file = process.env.WE_WEB_TOKEN_FILE ?? "../../.local/web-token";
  try {
    return readFileSync(file, "utf8").trim() || null;
  } catch {
    return null;
  }
}

export function api() {
  const t = token();
  if (!t) return null;
  return createWEClient({ baseUrl: process.env.WE_API_URL ?? "http://localhost:8000", token: t });
}

export const fmtDate = (iso?: string | null) =>
  iso ? new Intl.DateTimeFormat("pt-PT", { dateStyle: "short", timeStyle: "medium", timeZone: "Europe/Lisbon" }).format(new Date(iso)) : "—";

export const short = (id?: string | null) => (id ? `${id.slice(0, 8)}…` : "—");
