import { apiFetch, apiFetchJson } from "./client";
import type { EmpresaCriada, EmpresaDetalhe, Numeracao } from "./types";

export interface DadosEmpresaForm {
  cnpj: string;
  inscricao_municipal: string;
  municipio_ibge: string;
  local_prestacao_ibge: string;
  op_simp_nac: string;
  regime_apuracao_sn: string;
  codigo_tributacao: string;
  codigo_tributacao_municipal: string;
  descricao_servico_padrao: string;
  ambiente: string;
  senha_certificado: string;
  titular_email: string;
}

export type DadosEdicaoEmpresa = Omit<DadosEmpresaForm, "titular_email">;

export function criarEmpresa(dados: DadosEmpresaForm, pfx: File): Promise<EmpresaCriada> {
  const formulario = new FormData();
  const dadosLimpos = { ...dados, cnpj: dados.cnpj.replace(/\D/g, "") };
  Object.entries(dadosLimpos).forEach(([chave, valor]) => formulario.append(chave, valor));
  formulario.append("pfx", pfx);
  return apiFetch<EmpresaCriada>("/api/empresas", { method: "POST", body: formulario });
}

export function obterMinhaEmpresa(): Promise<EmpresaDetalhe> {
  return apiFetch<EmpresaDetalhe>("/api/empresas/mim");
}

export function editarEmpresa(dados: DadosEdicaoEmpresa, pfx: File | null): Promise<EmpresaDetalhe> {
  const formulario = new FormData();
  const dadosLimpos = { ...dados, cnpj: dados.cnpj.replace(/\D/g, "") };
  Object.entries(dadosLimpos).forEach(([chave, valor]) => formulario.append(chave, valor));
  if (pfx) {
    formulario.append("pfx", pfx);
  }
  return apiFetch<EmpresaDetalhe>("/api/empresas/mim", { method: "PUT", body: formulario });
}

export function obterNumeracao(): Promise<Numeracao> {
  return apiFetch<Numeracao>("/api/empresas/numeracao");
}

export function definirNumeracao(dados: Numeracao): Promise<Numeracao> {
  return apiFetchJson<Numeracao>("/api/empresas/numeracao", "PUT", dados);
}
