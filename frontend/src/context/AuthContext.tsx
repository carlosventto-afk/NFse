import { createContext, useContext, useEffect, useMemo, useState, type ReactNode } from "react";
import { decodificarJwt, type PayloadToken } from "../lib/jwt";
import { limparToken, obterToken, salvarToken } from "../api/client";
import { listarMinhasEmpresas, login as loginApi, trocarEmpresaApi } from "../api/auth";
import type { EmpresaVinculada } from "../api/types";

interface ContextoAuth {
  payload: PayloadToken | null;
  empresas: EmpresaVinculada[];
  carregando: boolean;
  login: (email: string, senha: string) => Promise<void>;
  logout: () => void;
  trocarEmpresa: (empresaId: string) => Promise<void>;
  recarregarEmpresas: () => Promise<void>;
}

const AuthContext = createContext<ContextoAuth | null>(null);

export function AuthProvider({ children }: { children: ReactNode }) {
  const [payload, setPayload] = useState<PayloadToken | null>(() => {
    const token = obterToken();
    return token ? decodificarJwt(token) : null;
  });
  const [empresas, setEmpresas] = useState<EmpresaVinculada[]>([]);
  const [carregando, setCarregando] = useState(true);

  async function recarregarEmpresas() {
    if (!obterToken()) {
      setEmpresas([]);
      return;
    }
    const lista = await listarMinhasEmpresas();
    setEmpresas(lista);
  }

  useEffect(() => {
    recarregarEmpresas().finally(() => setCarregando(false));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function login(email: string, senha: string) {
    const { access_token } = await loginApi(email, senha);
    salvarToken(access_token);
    setPayload(decodificarJwt(access_token));
    await recarregarEmpresas();
  }

  function logout() {
    limparToken();
    setPayload(null);
    setEmpresas([]);
  }

  async function trocarEmpresa(empresaId: string) {
    const { access_token } = await trocarEmpresaApi(empresaId);
    salvarToken(access_token);
    setPayload(decodificarJwt(access_token));
  }

  const valor = useMemo(
    () => ({ payload, empresas, carregando, login, logout, trocarEmpresa, recarregarEmpresas }),
    [payload, empresas, carregando]
  );

  return <AuthContext.Provider value={valor}>{children}</AuthContext.Provider>;
}

export function useAuth(): ContextoAuth {
  const contexto = useContext(AuthContext);
  if (!contexto) {
    throw new Error("useAuth precisa estar dentro de <AuthProvider>");
  }
  return contexto;
}
