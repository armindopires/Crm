# Classificação de dados e tratamento

| Classe | Exemplos | Armazenamento | Eventos / auditoria | Embeddings / índices | Logs |
|---|---|---|---|---|---|
| `public` | Catálogos de capacidades | Livre | Permitido | Permitido | Permitido |
| `internal` | Tipos de entidade, estados, métricas | Tabelas com RLS | Permitido | Permitido | Permitido |
| `confidential` | Dados de clientes, evidências comuns | RLS + habilitação ≥ confidential | Só referências e nomes de campos | Só campos não pessoais | Proibido |
| `restricted` | NIF, NISS, IBAN, dados laborais e de saúde | `kernel.entity_identifiers`, RLS + ABAC (finalidade) | Proibido (pseudónimo/hash) | **Excluído** | Proibido (redação) |
| `secret` | Passwords, tokens, chaves, certificados | **Nunca na WE**: só referências de cofre | Proibido | Proibido | Proibido (redação) |

## Regras operacionais
- Seeds e fixtures usam exclusivamente dados fictícios: domínios `.invalid`/`.example.invalid`, NIF de teste
  `999999990` apenas como valor a excluir e nomes claramente fictícios.
- Pseudonimização na auditoria: `HMAC-SHA256(WE_AUDIT_PSEUDONYM_KEY, sujeito)`. A rotação da chave quebra a
  correlação histórica e deve ser documentada (runbook de rotação).
- **RGPD.** Direitos de acesso, retificação, apagamento e portabilidade são capacidades futuras documentadas.
  O apagamento atua sobre tabelas de estado. Eventos e auditoria não contêm PII (ADR-0013), pelo que a
  integridade probatória se mantém. Crypto-shredding por sujeito fica previsto para dados `restricted` quando
  for necessário guardá-los em evidências.
- **Retenção.** `evidence.retention_class` existe (por omissão `NAO_INDICADO`). Os prazos legais (fiscais,
  contabilísticos, laborais) exigem **validação jurídica humana** e fonte oficial antes de serem configurados.
- **AIPD/DPIA.** É obrigatória antes de: integrar um LLM externo, tratar dados laborais ou de saúde, ativar
  conectores externos ou fazer migrações reais de clientes.
