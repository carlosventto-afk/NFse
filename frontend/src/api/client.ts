const CHAVE_TOKEN = "nfse.token";

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function obterToken(): string | null {
  return localStorage.getItem(CHAVE_TOKEN);
}

export function salvarToken(token: string): void {
  localStorage.setItem(CHAVE_TOKEN, token);
}

export function limparToken(): void {
  localStorage.removeItem(CHAVE_TOKEN);
}

async function tratarResposta<T>(resposta: Response): Promise<T> {
  if (resposta.status === 401) {
    limparToken();
    window.location.href = "/login";
    throw new ApiError(401, "Sessao expirada");
  }
  if (!resposta.ok) {
    let detalhe = resposta.statusText;
    try {
      const corpo = await resposta.json();
      detalhe = corpo.detail ?? JSON.stringify(corpo);
    } catch {
      // corpo nao era JSON, mantem o statusText
    }
    throw new ApiError(resposta.status, detalhe);
  }
  if (resposta.status === 204) {
    return undefined as T;
  }
  return (await resposta.json()) as T;
}

export async function apiFetch<T>(caminho: string, opcoes: RequestInit = {}): Promise<T> {
  const token = obterToken();
  const cabecalhos = new Headers(opcoes.headers);
  if (token) {
    cabecalhos.set("Authorization", `Bearer ${token}`);
  }
  const resposta = await fetch(caminho, { ...opcoes, headers: cabecalhos });
  return tratarResposta<T>(resposta);
}

export async function apiFetchJson<T>(
  caminho: string, metodo: string, corpo: unknown
): Promise<T> {
  return apiFetch<T>(caminho, {
    method: metodo,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(corpo),
  });
}
