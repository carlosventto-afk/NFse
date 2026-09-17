import { apiFetch } from "./client";
import type { Plano } from "./types";

export function listarPlanos(): Promise<Plano[]> {
  return apiFetch<Plano[]>("/api/planos");
}
