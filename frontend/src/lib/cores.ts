// Cores por identidade (nunca por posicao/ranking) -- uma categoria sempre
// tem a mesma cor, mesmo que a ordem dela mude ao trocar de competencia.
// Extensao harmonica do acento da marca (--acento: #2fa98c).

export const COR_PADRAO = "#8c98a4";

export const CORES_TIPO_PRODUTO: Record<string, string> = {
  Debito: "#2fa98c",
  Credito: "#4a5fd1",
  PIX: "#c98a2b",
};

export const CORES_BANDEIRA: Record<string, string> = {
  Visa: "#4a5fd1",
  MasterCard: "#c1502e",
  Elo: "#2fa98c",
  Stone: "#c98a2b",
};

export function corPorChave(mapa: Record<string, string>, chave: string | null): string {
  if (chave === null) return COR_PADRAO;
  return mapa[chave] ?? COR_PADRAO;
}
