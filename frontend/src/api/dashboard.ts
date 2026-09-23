import { apiFetch } from "./client";
import type { DashboardResumo } from "./types";

export function buscarResumoDashboard(competencia: string): Promise<DashboardResumo> {
  const parametros = new URLSearchParams({ competencia });
  return apiFetch<DashboardResumo>(`/api/dashboard/resumo?${parametros.toString()}`);
}
