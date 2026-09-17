import { apiFetchJson } from "./client";
import type { ConviteOut } from "./types";

export function aceitarConvite(token: string, senha?: string): Promise<ConviteOut> {
  return apiFetchJson<ConviteOut>("/api/convites/aceitar", "POST", { token, senha });
}

export function convidarTitular(email: string, planoId: string): Promise<ConviteOut> {
  return apiFetchJson<ConviteOut>("/api/convites", "POST", { email, plano_id: planoId });
}
