import { apiFetchJson } from "./client";
import type { ConviteOut } from "./types";

export function aceitarConvite(token: string, senha?: string): Promise<ConviteOut> {
  return apiFetchJson<ConviteOut>("/api/convites/aceitar", "POST", { token, senha });
}
