import { apiFetch } from "./client";
import type { ResultadoImportacaoCsv } from "./types";

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
