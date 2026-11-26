import { api, fmtDate, short } from "@/lib/api";
import { ApiError, NoToken } from "../no-token";

export default async function Lotes() {
  const c = api();
  if (!c) return <NoToken />;
  const [b, ss] = await Promise.all([c.GET("/v1/import-batches"), c.GET("/v1/source-systems")]);
  if (!b.data || !ss.data) return <ApiError status={b.response.status} />;
  return (
    <>
      <h1>Ingestão e reconciliação</h1>
      <p className="lead">Lotes de staging por sistema de origem. Nenhuma ligação a bases reais nesta fase.</p>
      <h2>Lotes</h2>
      <div className="table-wrap"><table>
        <thead><tr><th>Lote</th><th>Origem</th><th>Tipo</th><th>Estado</th><th>Lidos</th><th>Aceites</th><th>Rejeitados</th><th>Órfãos</th><th>Criado</th></tr></thead>
        <tbody>{b.data.items.map((x) => (
          <tr key={x.batch_id}><td className="mono">{short(x.batch_id)}</td><td>{x.source_system_code}</td><td>{x.batch_kind}</td>
            <td><span className={`badge ${x.status === "reconciled" ? "ok" : x.status === "failed" ? "bad" : "warn"}`}>{x.status}</span></td>
            <td>{x.counts.read ?? 0}</td><td>{x.counts.accepted ?? 0}</td><td>{x.counts.rejected ?? 0}</td><td>{x.counts.orphans ?? 0}</td><td>{fmtDate(x.created_at)}</td></tr>))}
          {b.data.items.length === 0 && <tr><td colSpan={9} className="muted">Sem lotes. Importe um depósito com <code>we import-knowledge</code>.</td></tr>}</tbody>
      </table></div>
      <h2>Sistemas de origem</h2>
      <div className="table-wrap"><table>
        <thead><tr><th>Código</th><th>Sistema</th><th>Tecnologia</th><th>Papel na Fase 1</th><th>Notas</th></tr></thead>
        <tbody>{ss.data.items.map((x) => <tr key={x.source_system_code}><td className="mono">{x.source_system_code}</td><td>{x.name}</td><td>{x.technology}</td><td>{x.role_in_phase1}</td><td>{x.notes_pt}</td></tr>)}</tbody>
      </table></div>
    </>
  );
}
