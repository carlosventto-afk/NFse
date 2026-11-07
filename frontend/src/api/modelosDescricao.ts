import { apiFetch, apiFetchJson } from "./client";
import type { ModeloDescricao, ModeloDescricaoForm } from "./types";

export function listarModelosDescricao(): Promise<ModeloDescricao[]> {
  return apiFetch<ModeloDescricao[]>("/api/modelos-descricao");
}

export function criarModeloDescricao(dados: ModeloDescricaoForm): Promise<ModeloDescricao> {
  return apiFetchJson<ModeloDescricao>("/api/modelos-descricao", "POST", dados);
}

export function atualizarModeloDescricao(id: string, dados: ModeloDescricaoForm): Promise<ModeloDescricao> {
  return apiFetchJson<ModeloDescricao>(`/api/modelos-descricao/${id}`, "PUT", dados);
}

export function removerModeloDescricao(id: string): Promise<void> {
  return apiFetch<void>(`/api/modelos-descricao/${id}`, { method: "DELETE" });
}
