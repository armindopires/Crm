import { api } from "@/lib/api";
import { ApiError, NoToken } from "./no-token";

const LABELS: Record<string, string> = {
  entities: "Entidades", events: "Eventos", evidence: "Evidências", decisions_pending: "Decisões pendentes",
  signals: "Sinais", opportunities: "Oportunidades", import_batches: "Lotes de ingestão", audit_records: "Registos de auditoria",
};

export default async function Estado() {
  const c = api();
  if (!c) return <NoToken />;
  const [{ data, response }, health] = await Promise.all([
    c.GET("/v1/system/status"),
    fetch(`${process.env.WE_API_URL ?? "http://localhost:8000"}/health/ready`, { cache: "no-store" }).then((r) => r.json()).catch(() => null),
  ]);
  if (!data) return <ApiError status={response.status} />;
  return (
    <>
      <h1>Estado do sistema</h1>
      <p className="lead">Tenant <strong>{data.tenant.display_name}</strong> <span className="badge muted">{data.tenant.is_synthetic ? "sintético" : "real"}</span></p>
      <h2>Dependências</h2>
      <div className="grid">
        {Object.entries(health?.checks ?? {}).map(([k, v]) => (
          <div className="card" key={k}><div className="l">{k}</div><div className={`n ${v === "ok" ? "ok" : v === "degraded" ? "warn" : "bad"}`}>{String(v)}</div></div>
        ))}
        <div className="card"><div className="l">Cadeia de eventos</div><div className={`n ${data.chains.events ? "ok" : "bad"}`}>{data.chains.events ? "íntegra" : "ADULTERADA"}</div></div>
        <div className="card"><div className="l">Cadeia de auditoria</div><div className={`n ${data.chains.audit ? "ok" : "bad"}`}>{data.chains.audit ? "íntegra" : "ADULTERADA"}</div></div>
      </div>
      <h2>Volumes</h2>
      <div className="grid">
        {Object.entries(data.counts).map(([k, v]) => <div className="card" key={k}><div className="n">{v}</div><div className="l">{LABELS[k] ?? k}</div></div>)}
      </div>
      <h2>Outbox e projeções</h2>
      <div className="grid">
        <div className="card"><div className="n">{data.outbox.pending}</div><div className="l">Pendentes</div></div>
        <div className="card"><div className="n">{data.outbox.published}</div><div className="l">Publicadas</div></div>
        <div className="card"><div className={`n ${data.outbox.dead ? "bad" : ""}`}>{data.outbox.dead}</div><div className="l">Em DLQ</div></div>
        <div className="card"><div className="n">{data.outbox.projection_lag.lag}</div><div className="l">Atraso da projeção (eventos)</div></div>
      </div>
    </>
  );
}
