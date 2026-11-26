# ADR-0006 — Identidade OIDC; emissor de desenvolvimento sem passwords; IdP produtivo NAO_INDICADO

- **Estado:** aprovado para desenvolvimento; **IdP de produção por decidir** · **Evidência:** NAO_INDICADO (IdP)

## Decisão
- A API valida JWT (RS256/ES256) por JWKS, verificando `iss`, `aud`, `exp`, `nbf` e `kid`. `alg=none` e chaves
  desconhecidas são rejeitados.
- Em desenvolvimento existe uma chave RSA local (`.local/`, fora do Git), `we dev-token` e `we dev-idp`
  (discovery + JWKS, perfil `identity`). Não há login, passwords nem armazenamento de credenciais: a WE nunca
  gere passwords.
- Em staging e produção é obrigatório `WE_OIDC_JWKS_URL` (há guarda em `Settings`). O emissor de
  desenvolvimento recusa-se a funcionar fora de development/test.
- MFA, gestão de sessões e federação são delegadas ao IdP.
- A interface web de desenvolvimento usa um token de serviço local lido no servidor. Em produção será necessário
  um fluxo OIDC Authorization Code + PKCE com cookies `HttpOnly; Secure; SameSite=Strict` (pendente).

## Decisão necessária do utilizador
Que IdP usar (Entra ID, Keycloak, Authentik, Auth0…) e com que claims de tenant e de papéis.
