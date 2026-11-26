import { redirect } from "next/navigation";
import { api, fmtDate, short } from "@/lib/api";
import { ApiError, NoToken } from "../no-token";

async function verificar(formData: FormData) {
  "use server";
  const id = String(formData.get("evidence_id") ?? "");
  if (!/^[0-9a-f-]{36}$/i.test(id)) redirect("/evidencias");
  const c = api();
  const r = c ? await c.POST("/v1/evidence/{evidence_id}/verify", { params: { path: { evidence_id: id } } }) : null;
  redirect(`/evidencias?verificado=${id}&resultado=${r?.data?.result ?? "erro"}`);
}

export default async function Evidencias({ searchParams }: { searchParams: Promise<{ verificado?: string; resultado?: string }> }) {
  const { verificado, resultado } = await searchParams;
  const c = api();
  if (!c) return <NoToken />;
  const { data, response } = await c.GET("/v1/evidence", { params: { query: { limit: 100 } } });
  if (!data) return <ApiError status={response.status} />;
  return (
    <>
      <h1>Evidências</h1>
      <p className="lead">Objetos imutáveis com SHA-256 calculado no servidor. A verificação recalcula o hash do objeto guardado e fica registada na cadeia de custódia.</p>
      {verificado && (
        <p role="status" className={`notice ${resultado === "ok" ? "ok" : "bad"}`}>
          Evidência {short(verificado)}: {resultado === "ok" ? "integridade confirmada (SHA-256 coincide)." : `falha de integridade (${resultado}).`}
        </p>
      )}
      <div className="table-wrap"><table>
        <thead><tr><th>Evidência</th><th>Ficheiro</th><th>Tipo</th><th>Tamanho</th><th>Classificação</th><th>SHA-256</th><th>Carregada</th><th><span className="skip">Ações</span></th></tr></thead>
        <tbody>{data.items.map((e) => (
          <tr key={e.evidence_id}>
            <td className="mono">{short(e.evidence_id)}</td><td>{e.filename_safe}</td><td>{e.media_type}</td><td>{e.size_bytes} B</td>
            <td><span className="badge">{e.classification}</span></td><td className="mono" title={e.sha256}>{e.sha256.slice(0, 16)}…</td>
            <td>{fmtDate(e.uploaded_at)}</td>
            <td><form action={verificar}><input type="hidden" name="evidence_id" value={e.evidence_id} /><button type="submit" aria-label={`Verificar integridade de ${e.filename_safe}`}>Verificar</button></form></td>
          </tr>))}</tbody>
      </table></div>
    </>
  );
}
