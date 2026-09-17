import { apiFetchJson } from "./client";

export interface UsuarioCriado {
  id: string;
  email: string;
}

export function criarUsuario(email: string, senha: string, planoId: string): Promise<UsuarioCriado> {
  return apiFetchJson<UsuarioCriado>("/api/usuarios", "POST", { email, senha, plano_id: planoId });
}
