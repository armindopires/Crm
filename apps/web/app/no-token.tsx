export function NoToken() {
  return (
    <div className="notice" role="status">
      <p><strong>Sem sessão.</strong> Esta interface de desenvolvimento usa um token local gerado pela demonstração.</p>
      <p>Corra <code>python scripts/dev.py demo</code> e recarregue a página.</p>
    </div>
  );
}

export function ApiError({ status }: { status?: number }) {
  return <div className="notice" role="alert"><p>A API respondeu com erro{status ? ` (${status})` : ""}. Verifique se o perfil core está ativo.</p></div>;
}
