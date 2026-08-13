export interface PayloadToken {
  sub: string;
  eh_admin_plataforma: boolean;
  empresa_id: string | null;
  papel: "admin" | "operador" | null;
  exp: number;
}

// So decodifica o payload (base64url) para uso na UI — nao verifica
// assinatura. A aplicacao da autorizacao de verdade e sempre feita pela
// API; isto e so para a SPA saber o contexto do token que ja tem.
export function decodificarJwt(token: string): PayloadToken {
  const [, payloadB64] = token.split(".");
  const normalizado = payloadB64.replace(/-/g, "+").replace(/_/g, "/");
  const json = atob(normalizado);
  return JSON.parse(json) as PayloadToken;
}
