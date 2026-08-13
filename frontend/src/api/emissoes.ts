import { apiFetch, apiFetchJson } from "./client";
import type { Emissao, ResultadoImportacaoCsv } from "./types";

function formularioComArquivo(arquivo: File): FormData {
  const formulario = new FormData();
  formulario.append("arquivo", arquivo);
  return formulario;
}

export function previewCsv(arquivo: File): Promise<ResultadoImportacaoCsv> {
  return apiFetch<ResultadoImportacaoCsv>("/api/emissoes/csv/preview", {
    method: "POST", body: formularioComArquivo(arquivo),
  });
}

export function confirmarCsv(arquivo: File): Promise<ResultadoImportacaoCsv> {
  return apiFetch<ResultadoImportacaoCsv>("/api/emissoes/csv/confirmar", {
    method: "POST", body: formularioComArquivo(arquivo),
  });
}

export async function listarEmissoes(status?: string): Promise<Emissao[]> {
  const parametros = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiFetch<Emissao[]>(`/api/emissoes${parametros}`);
}

export function cancelarEmissao(id: string, motivo: string, codigoMotivo: string): Promise<Emissao> {
  return apiFetchJson<Emissao>(`/api/emissoes/${id}/cancelar`, "POST", {
    motivo, codigo_motivo: codigoMotivo,
  });
}

export function urlXml(id: string): string {
  return `/api/emissoes/${id}/xml`;
}

export function urlPdf(id: string): string {
  return `/api/emissoes/${id}/pdf`;
}
