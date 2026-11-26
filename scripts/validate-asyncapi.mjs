// Valida o contrato AsyncAPI (incluindo $ref para os JSON Schema de eventos).
import { Parser, fromFile } from "@asyncapi/parser";

const parser = new Parser();
const { document, diagnostics } = await fromFile(parser, "contracts/asyncapi/we-events.v1.json").parse();
const errors = diagnostics.filter((d) => d.severity === 0);
for (const d of diagnostics.filter((d) => d.severity <= 1)) console.log(`[${d.severity === 0 ? "ERRO" : "AVISO"}] ${d.message} @ ${d.path?.join(".")}`);
if (!document || errors.length) {
  console.error(`AsyncAPI inválido: ${errors.length} erro(s)`);
  process.exit(1);
}
console.log(`AsyncAPI válido: ${document.channels().length} canais, ${document.components().messages().length} mensagens`);
