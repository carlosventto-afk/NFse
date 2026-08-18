export interface TokenOut {
  access_token: string;
  token_type: string;
}

export interface EmpresaVinculada {
  empresa_id: string;
  cnpj: string;
  papel: "admin" | "operador";
}

export interface Cliente {
  id: string;
  cpf_cnpj: string | null;
  nome: string;
  email: string | null;
  telefone: string | null;
  inscricao_estadual: string | null;
  inscricao_municipal: string | null;
  logradouro: string | null;
  numero: string | null;
  complemento: string | null;
  bairro: string | null;
  municipio_ibge: string | null;
  uf: string | null;
  cep: string | null;
  ativo: boolean;
}

export type ClienteForm = Omit<Cliente, "id" | "ativo"> & { ativo?: boolean };

export interface Emissao {
  id: string;
  origem: string;
  status: string;
  serie: string | null;
  numero: number | null;
  chave_acesso: string | null;
  tomador_cpf_cnpj: string | null;
  tomador_nome: string | null;
  descricao: string;
  valor: string;
  competencia: string;
  erros: string | null;
}

export interface ResultadoImportacaoCsv {
  total_notas: number;
  valor_total: string;
  ignoradas: {
    status_nao_pago: number;
    categoria_nao_venda: number;
    linha_invalida: number;
    ja_emitida_anteriormente: number;
  };
}

export interface ConviteOut {
  id: string;
  email: string;
  empresa_id: string | null;
  papel: string | null;
  expira_em: string;
}

export interface EmpresaCriada {
  id: string;
  cnpj: string;
  ambiente: string;
}

export interface Numeracao {
  serie: string;
  proximo_numero: number;
}

export interface EmpresaDetalhe {
  id: string;
  cnpj: string;
  inscricao_municipal: string | null;
  municipio_ibge: string;
  op_simp_nac: number;
  codigo_tributacao: string;
  descricao_servico_padrao: string;
  ambiente: string;
  certificado_valido_ate: string;
}
