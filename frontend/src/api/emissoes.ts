import { apiFetch, apiFetchJson } from "./client";
import type { Emissao, EmissaoLoteResultado, ExclusaoLoteResultado, ResultadoImportacaoCsv } from "./types";

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

export type TipoFiltroData = "competencia" | "data_venda";

export async function listarEmissoes(
  status?: string, tipoData?: TipoFiltroData, inicio?: string, fim?: string,
): Promise<Emissao[]> {
  const parametros = new URLSearchParams();
  if (status) parametros.set("status", status);
  const prefixo = tipoData === "data_venda" ? "vencimento" : "competencia";
  if (inicio) parametros.set(`${prefixo}_inicio`, inicio);
  if (fim) parametros.set(`${prefixo}_fim`, fim);
  const query = parametros.toString();
  return apiFetch<Emissao[]>(`/api/emissoes${query ? `?${query}` : ""}`);
}

export function cancelarEmissao(id: string, motivo: string, codigoMotivo: string): Promise<Emissao> {
  return apiFetchJson<Emissao>(`/api/emissoes/${id}/cancelar`, "POST", {
    motivo, codigo_motivo: codigoMotivo,
  });
}

export function excluirEmissao(id: string): Promise<void> {
  return apiFetch<void>(`/api/emissoes/${id}`, { method: "DELETE" });
}

export function excluirEmissoesLote(ids: string[]): Promise<ExclusaoLoteResultado> {
  return apiFetchJson<ExclusaoLoteResultado>("/api/emissoes/excluir-lote", "POST", { ids });
}

export function emitirEmissao(id: string): Promise<Emissao> {
  return apiFetchJson<Emissao>(`/api/emissoes/${id}/emitir`, "POST", {});
}

export function emitirEmissoesLote(ids: string[]): Promise<EmissaoLoteResultado> {
  return apiFetchJson<EmissaoLoteResultado>("/api/emissoes/emitir-lote", "POST", { ids });
}

export function urlXml(id: string): string {
  return `/api/emissoes/${id}/xml`;
}

export function urlPdf(id: string): string {
  return `/api/emissoes/${id}/pdf`;
}

export function urlRespostaBruta(id: string): string {
  return `/api/emissoes/${id}/resposta-bruta`;
}

export function urlRequisicaoBruta(id: string): string {
  return `/api/emissoes/${id}/requisicao-bruta`;
}

export function urlDownloadXmlsLote(): string {
  return `/api/emissoes/download-xmls`;
}

export function urlDownloadPdfsLote(): string {
  return `/api/emissoes/download-pdfs`;
}
