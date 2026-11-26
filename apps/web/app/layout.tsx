import type { Metadata } from "next";
import type { ReactNode } from "react";
import "./globals.css";

export const metadata: Metadata = { title: "WE · Consola operacional", description: "Wolf Enterprise — interface operacional mínima" };
export const dynamic = "force-dynamic";

const links: [string, string][] = [
  ["/", "Estado"], ["/eventos", "Eventos"], ["/evidencias", "Evidências"], ["/decisoes", "Decisões"],
  ["/sinais", "Sinais e oportunidades"], ["/lotes", "Ingestão e reconciliação"],
];

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="pt-PT">
      <body>
        <a className="skip" href="#conteudo">Saltar para o conteúdo</a>
        <header>
          <div className="bar">
            <strong>Wolf Enterprise</strong>
            <nav aria-label="Navegação principal"><ul>{links.map(([href, label]) => <li key={href}><a href={href}>{label}</a></li>)}</ul></nav>
          </div>
        </header>
        <main id="conteudo">{children}</main>
      </body>
    </html>
  );
}
