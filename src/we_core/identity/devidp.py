"""IdP de desenvolvimento (perfil `identity`): serve discovery OIDC e JWKS. Sem passwords nem login.

Os tokens são emitidos por `we dev-token` (CLI) com a mesma chave. Proibido fora de development/test.
"""

from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from we_core.config import Settings


def serve(settings: Settings, host: str, port: int) -> None:
    if settings.env not in ("development", "test"):
        raise SystemExit("dev-idp proibido fora de development/test")
    jwks = Path(".local/dev-jwks.json").read_bytes()
    discovery = json.dumps(
        {
            "issuer": settings.oidc_issuer,
            "jwks_uri": f"http://{host}:{port}/.well-known/jwks.json",
            "id_token_signing_alg_values_supported": ["RS256"],
            "subject_types_supported": ["public"],
            "response_types_supported": ["token"],
        }
    ).encode()

    class H(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            body = {"/.well-known/jwks.json": jwks, "/.well-known/openid-configuration": discovery}.get(
                self.path
            )
            self.send_response(200 if body else 404)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(body or b"{}")

    ThreadingHTTPServer((host, port), H).serve_forever()
