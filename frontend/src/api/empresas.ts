import { apiFetch } from "./client";
import type { EmpresaCriada } from "./types";

export interface DadosEmpresaForm {
  cnpj: string;
  inscricao_municipal: string;
  municipio_ibge: string;
  op_simp_nac: string;
  codigo_tributacao: string;
  descricao_servico_padrao: string;
  ambiente: string;
  senha_certificado: string;
  titular_email: string;
}

export function criarEmpresa(dados: DadosEmpresaForm, pfx: File): Promise<EmpresaCriada> {
  const formulario = new FormData();
  const dadosLimpos = { ...dados, cnpj: dados.cnpj.replace(/\D/g, "") };
  Object.entries(dadosLimpos).forEach(([chave, valor]) => formulario.append(chave, valor));
  formulario.append("pfx", pfx);
  return apiFetch<EmpresaCriada>("/api/empresas", { method: "POST", body: formulario });
}
