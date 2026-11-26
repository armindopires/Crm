/**
 * SDK TypeScript da WE — tipos gerados de contracts/openapi/we-api.v1.json (sem duplicação manual).
 * Regenerar: `pnpm --filter @we/sdk generate` (ou `python scripts/dev.py contracts`).
 */
import createClient from "openapi-fetch";
import type { components, paths } from "./schema";

export type { components, paths };
export type Schemas = components["schemas"];

export interface WEClientOptions {
  baseUrl: string;
  token: string;
  correlationId?: string;
  purpose?: string;
}

export function createWEClient(opts: WEClientOptions) {
  const headers: Record<string, string> = { Authorization: `Bearer ${opts.token}` };
  if (opts.correlationId) headers["X-Correlation-ID"] = opts.correlationId;
  if (opts.purpose) headers["X-WE-Purpose"] = opts.purpose;
  return createClient<paths>({ baseUrl: opts.baseUrl, headers });
}
