import { api, fmtDate, short } from "@/lib/api";
import { ApiError, NoToken } from "../no-token";

export default async function Eventos({ searchParams }: { searchParams: Promise<{ correlation_id?: string }> }) {
  const { correlation_id } = await searchParams;
  const c = api();
  if (!c) return <NoToken />;
  const valid = correlation_id && /^[0-9a-f-]{36}$/i.test(correlation_id) ? correlation_id : undefined;
  const { data, response } = await c.GET("/v1/events", { params: { query: { limit: 200, correlation_id: valid } } });
  if (!data) return <ApiError status={response.status} />;
  return (
    <>
      <h1>Eventos</h1>
      <p className="lead">Event Store append-only, ordenado por sequência da cadeia de integridade.</p>
      <form className="inline" method="get" role="search">
        <label>Correlação<br /><input name="correlation_id" defaultValue={valid ?? ""} placeholder="UUID de correlação" /></label>
        <button type="submit">Filtrar</button> {valid && <a href="/eventos">Limpar</a>}
      </form>
      <div className="table-wrap"><table>
        <caption className="skip">Lista de eventos</caption>
        <thead><tr><th>#</th><th>Tipo</th><th>Agregado</th><th>Versão</th><th>Ator</th><th>Ocorreu</th><th>Correlação</th><th>Hash</th></tr></thead>
        <tbody>{data.items.map((e) => (
          <tr key={e.event_id}>
            <td className="mono">{e.chain_seq}</td><td><code>{e.event_type}</code> <span className="muted">v{e.schema_version}</span></td>
            <td className="mono">{e.aggregate_type}/{short(e.aggregate_id)}</td><td>{e.aggregate_version}</td><td>{e.actor_type}</td>
            <td>{fmtDate(e.occurred_at)}</td><td><a className="mono" href={`/eventos?correlation_id=${e.correlation_id}`}>{short(e.correlation_id)}</a></td>
            <td className="mono">{e.event_hash.slice(0, 12)}</td>
          </tr>))}</tbody>
      </table></div>
    </>
  );
}
