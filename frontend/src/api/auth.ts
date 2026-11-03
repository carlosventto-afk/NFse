import { apiFetch, apiFetchJson } from "./client";
import type { EmpresaVinculada, TokenOut } from "./types";

export async function login(email: string, senha: string): Promise<TokenOut> {
  const corpo = new URLSearchParams({ username: email, password: senha });
  const resposta = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body: corpo.toString(),
  });
  if (!resposta.ok) {
    const erro = await resposta.json().catch(() => ({ detail: "Credenciais invalidas" }));
    throw new Error(erro.detail ?? "Credenciais invalidas");
  }
  return resposta.json();
}

export function listarMinhasEmpresas(): Promise<EmpresaVinculada[]> {
  return apiFetch<EmpresaVinculada[]>("/api/auth/empresas");
}

export function trocarEmpresaApi(empresaId: string): Promise<TokenOut> {
  return apiFetchJson<TokenOut>("/api/auth/trocar-empresa", "POST", { empresa_id: empresaId });
}

export function esqueciSenha(email: string): Promise<void> {
  return apiFetchJson<void>("/api/auth/esqueci-senha", "POST", { email });
}

export function redefinirSenha(token: string, novaSenha: string): Promise<void> {
  return apiFetchJson<void>("/api/auth/redefinir-senha", "POST", { token, nova_senha: novaSenha });
}
