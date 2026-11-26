/** Interface operacional mínima da WE. Renderização no servidor; o token nunca chega ao browser. */
const securityHeaders = [
  { key: "Content-Security-Policy", value: "default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; form-action 'self'" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "no-referrer" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
];
export default {
  output: "standalone",
  poweredByHeader: false,
  transpilePackages: ["@we/sdk"],
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};
