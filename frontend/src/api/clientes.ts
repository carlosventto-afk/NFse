import { apiFetch, apiFetchJson } from "./client";
import type { Cliente, ClienteForm } from "./types";

export function listarClientes(): Promise<Cliente[]> {
  return apiFetch<Cliente[]>("/api/clientes");
}

export function criarCliente(dados: ClienteForm): Promise<Cliente> {
  return apiFetchJson<Cliente>("/api/clientes", "POST", dados);
}

export function atualizarCliente(id: string, dados: ClienteForm & { ativo: boolean }): Promise<Cliente> {
  return apiFetchJson<Cliente>(`/api/clientes/${id}`, "PUT", dados);
}
