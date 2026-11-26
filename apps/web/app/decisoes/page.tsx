import { api, fmtDate, short } from "@/lib/api";
import { ApiError, NoToken } from "../no-token";

const STATUS: Record<string, string> = { proposed: "proposta", under_review: "em revisão", approved: "aprovada", rejected: "rejeitada", executed: "executada", superseded: "substituída" };

export default async function Decisoes() {
  const c = api();
  if (!c) return <NoToken />;
  const { data, response } = await c.GET("/v1/decisions", { params: { query: { limit: 100 } } });
  if (!data) return <ApiError status={response.status} />;
  const pending = data.items.filter((d) => d.status === "proposed" || d.status === "under_review");
  return (
    <>
      <h1>Decisões</h1>
      <p className="lead">A IA propõe, o humano valida, o sistema audita. {pending.length} decisão(ões) a aguardar aprovação humana.</p>
      <div className="notice"><p>A aprovação exige uma identidade humana com papel <code>approver</code> e não pode ser feita pelo proponente. Esta consola de desenvolvimento é só de leitura; a aprovação faz-se em <code>POST /v1/decisions/&#123;id&#125;/review</code>.</p></div>
      <h2>Registo</h2>
      <div className="table-wrap"><table>
        <thead><tr><th>Decisão</th><th>Título</th><th>Impacto</th><th>Estado</th><th>Proposta por</th><th>AI_TRACE</th><th>Decidida</th><th>Fundamentação</th></tr></thead>
        <tbody>{data.items.map((d) => (
          <tr key={d.decision_id}>
            <td className="mono">{short(d.decision_id)}</td><td>{d.title}</td><td><span className="badge">{d.impact_category}</span></td>
            <td><span className={`badge ${d.status === "executed" || d.status === "approved" ? "ok" : d.status === "rejected" ? "bad" : "warn"}`}>{STATUS[d.status] ?? d.status}</span></td>
            <td>{d.proposed_by_type}</td><td className="mono">{short(d.ai_trace_id)}</td><td>{fmtDate(d.decided_at)}</td><td>{d.rationale ?? "—"}</td>
          </tr>))}</tbody>
      </table></div>
    </>
  );
}
