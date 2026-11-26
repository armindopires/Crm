import { api, fmtDate, short } from "@/lib/api";
import { ApiError, NoToken } from "../no-token";

const eur = (v?: string | null, cur?: string | null) =>
  v && cur ? new Intl.NumberFormat("pt-PT", { style: "currency", currency: cur }).format(Number(v)) : "—";

export default async function Sinais() {
  const c = api();
  if (!c) return <NoToken />;
  const [s, o] = await Promise.all([c.GET("/v1/signals", { params: { query: { limit: 100 } } }), c.GET("/v1/opportunities", { params: { query: { limit: 100 } } })]);
  if (!s.data || !o.data) return <ApiError status={s.response.status} />;
  return (
    <>
      <h1>Sinais e oportunidades</h1>
      <p className="lead">Piloto: sinais detetados e respetiva promoção a oportunidade.</p>
      <h2>Sinais</h2>
      <div className="table-wrap"><table>
        <thead><tr><th>Sinal</th><th>Tipo</th><th>Intensidade</th><th>Descrição</th><th>Estado</th><th>Criado</th></tr></thead>
        <tbody>{s.data.items.map((x) => <tr key={x.signal_id}><td className="mono">{short(x.signal_id)}</td><td><code>{x.signal_type}</code></td><td>{x.strength}</td><td>{x.description}</td><td><span className="badge">{x.status}</span></td><td>{fmtDate(x.created_at)}</td></tr>)}</tbody>
      </table></div>
      <h2>Oportunidades</h2>
      <div className="table-wrap"><table>
        <thead><tr><th>Oportunidade</th><th>Título</th><th>Valor estimado</th><th>Estado</th><th>Sinal de origem</th></tr></thead>
        <tbody>{o.data.items.map((x) => <tr key={x.opportunity_id}><td className="mono">{short(x.opportunity_id)}</td><td>{x.title}</td><td>{eur(x.value_estimate, x.currency)}</td><td><span className="badge">{x.status}</span></td><td className="mono">{short(x.signal_id)}</td></tr>)}</tbody>
      </table></div>
    </>
  );
}
