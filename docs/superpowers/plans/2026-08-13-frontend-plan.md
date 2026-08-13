# Frontend React — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Construir a SPA React que consome a API já pronta sob `/api/*`: login/multiempresa, aceitar convite, cadastro de empresa, cadastro de clientes, importação de CSV e gestão de emissões (com cancelamento).

**Architecture:** SPA React + Vite + TypeScript em `frontend/`, sem framework de estado global — `AuthContext` (Context API) guarda o token, o usuário decodificado do JWT e a lista de empresas. Um client HTTP fino centraliza a chamada à API e a injeção do `Authorization`. Em dev, Vite roda em `5173` com proxy para a API em `8000`; em produção, o build estático é servido pelo próprio FastAPI (Task 9).

**Tech Stack:** React 18, Vite, TypeScript, react-router-dom. Sem UI framework — CSS simples em um único arquivo. Sem suíte de testes automatizada nesta fase (decisão da spec) — verificação final via Playwright CLI contra build+preview (nunca contra o dev server).

## Global Constraints

- Todo endpoint da API já vive sob `/api/*` (ver
  `docs/superpowers/plans/2026-08-13-clientes-cancelamento-api-plan.md`,
  já implementado nesta branch).
- `POST /api/auth/login` usa `application/x-www-form-urlencoded`
  (`OAuth2PasswordRequestForm`), não JSON — campos `username`/`password`.
- Sem tela de "criar convite" nesta fase — só "aceitar convite" (a spec
  não incluiu essa tela; convites continuam sendo criados via API
  diretamente).
- Emissão manual via formulário está fora de escopo — só importação de
  CSV.
- Nenhuma suíte automatizada de frontend é commitada nesta fase; a
  verificação final (Task 9) usa Playwright de forma pontual (CLI, contra
  `npm run build && npm run preview`, nunca contra `npm run dev`) e não
  deixa arquivos de teste permanentes no repositório.

---

## Estrutura de arquivos

```
frontend/
  package.json
  vite.config.ts
  tsconfig.json
  tsconfig.node.json
  index.html
  src/
    main.tsx
    App.tsx                       # rotas
    index.css                     # estilo unico, minimo
    lib/
      jwt.ts                      # decodifica o payload do JWT (sem verificar assinatura)
    api/
      client.ts                   # fetch wrapper: injeta Authorization, trata 401
      types.ts                    # interfaces espelhando os schemas do backend
      auth.ts                     # login, listarEmpresas, trocarEmpresa
      convites.ts                 # aceitarConvite
      clientes.ts                 # CRUD de clientes
      emissoes.ts                 # csv preview/confirmar, listar, cancelar, urls de download
      empresas.ts                 # criar empresa (multipart)
    context/
      AuthContext.tsx             # usuario decodificado, empresas, login/logout/trocarEmpresa
    components/
      Layout.tsx                  # nav: empresa ativa, trocar empresa, sair
      RotaProtegida.tsx           # redireciona para /login se nao autenticado
    pages/
      LoginPage.tsx
      SelecionarEmpresaPage.tsx
      AceitarConvitePage.tsx
      CadastroEmpresaPage.tsx
      ClientesPage.tsx
      ImportarCsvPage.tsx
      EmissoesPage.tsx
app/
  main.py                          # MODIFICADO (Task 9) — StaticFiles + fallback de index.html
```

---

### Task 1: Scaffold do projeto (Vite + React + TypeScript)

**Files:**
- Create: `frontend/package.json`, `frontend/vite.config.ts`,
  `frontend/tsconfig.json`, `frontend/tsconfig.node.json`,
  `frontend/index.html`, `frontend/src/main.tsx`, `frontend/src/App.tsx`,
  `frontend/src/index.css`

**Interfaces:**
- Produces: projeto Vite funcional, `npm run dev`/`npm run build`
  operacionais.

- [ ] **Step 1: Criar `frontend/package.json`**

```json
{
  "name": "nfse-frontend",
  "private": true,
  "version": "0.0.1",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "tsc -b && vite build",
    "preview": "vite preview --port 4173"
  },
  "dependencies": {
    "react": "^18.3.1",
    "react-dom": "^18.3.1",
    "react-router-dom": "^6.26.0"
  },
  "devDependencies": {
    "@types/react": "^18.3.5",
    "@types/react-dom": "^18.3.0",
    "@vitejs/plugin-react": "^4.3.1",
    "typescript": "^5.5.4",
    "vite": "^5.4.2"
  }
}
```

- [ ] **Step 2: Criar `frontend/vite.config.ts`**

```typescript
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
    },
  },
  build: {
    outDir: "dist",
  },
});
```

- [ ] **Step 3: Criar `frontend/tsconfig.json`**

```json
{
  "compilerOptions": {
    "target": "ES2020",
    "useDefineForClassFields": true,
    "lib": ["ES2020", "DOM", "DOM.Iterable"],
    "module": "ESNext",
    "skipLibCheck": true,
    "moduleResolution": "bundler",
    "resolveJsonModule": true,
    "isolatedModules": true,
    "noEmit": true,
    "jsx": "react-jsx",
    "strict": true,
    "noUnusedLocals": true,
    "noUnusedParameters": true,
    "noFallthroughCasesInSwitch": true
  },
  "include": ["src"],
  "references": [{ "path": "./tsconfig.node.json" }]
}
```

- [ ] **Step 4: Criar `frontend/tsconfig.node.json`**

```json
{
  "compilerOptions": {
    "composite": true,
    "skipLibCheck": true,
    "module": "ESNext",
    "moduleResolution": "bundler",
    "allowSyntheticDefaultImports": true
  },
  "include": ["vite.config.ts"]
}
```

- [ ] **Step 5: Criar `frontend/index.html`**

```html
<!doctype html>
<html lang="pt-BR">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>NFS-e Automatizada</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.tsx"></script>
  </body>
</html>
```

- [ ] **Step 6: Criar `frontend/src/index.css`**

```css
* { box-sizing: border-box; }
body {
  margin: 0;
  font-family: system-ui, -apple-system, sans-serif;
  background: #f4f5f7;
  color: #1a1a1a;
}
a { color: #2563eb; }
input, select, button {
  font: inherit;
  padding: 0.5rem;
  border: 1px solid #ccc;
  border-radius: 4px;
}
button {
  cursor: pointer;
  background: #2563eb;
  color: white;
  border: none;
}
button:disabled { background: #94a3b8; cursor: not-allowed; }
button.secundario { background: #64748b; }
button.perigo { background: #dc2626; }
table { border-collapse: collapse; width: 100%; background: white; }
th, td { padding: 0.5rem; border-bottom: 1px solid #e5e7eb; text-align: left; }
.erro { color: #dc2626; margin: 0.5rem 0; }
.cartao { background: white; padding: 1.5rem; border-radius: 8px; max-width: 480px; margin: 2rem auto; }
.form-linha { display: flex; flex-direction: column; gap: 0.25rem; margin-bottom: 0.75rem; }
.nav { display: flex; justify-content: space-between; align-items: center; padding: 1rem 1.5rem; background: white; border-bottom: 1px solid #e5e7eb; }
.nav a { margin-right: 1rem; text-decoration: none; }
.conteudo { padding: 1.5rem; }
```

- [ ] **Step 7: Criar `frontend/src/App.tsx` (placeholder, expandido na Task 3)**

```typescript
export default function App() {
  return <p>NFS-e Automatizada</p>;
}
```

- [ ] **Step 8: Criar `frontend/src/main.tsx`**

```typescript
import React from "react";
import ReactDOM from "react-dom/client";
import App from "./App";
import "./index.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
```

- [ ] **Step 9: Instalar dependências e verificar o build**

```bash
cd frontend
npm install
npm run build
```

Expected: build conclui sem erros, gera `frontend/dist/index.html` e
assets.

- [ ] **Step 10: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/vite.config.ts \
        frontend/tsconfig.json frontend/tsconfig.node.json frontend/index.html \
        frontend/src/main.tsx frontend/src/App.tsx frontend/src/index.css frontend/.gitignore
git commit -m "chore: scaffold do frontend (Vite + React + TypeScript)"
```

Antes do commit, criar `frontend/.gitignore`:

```
node_modules
dist
```

---

### Task 2: Client HTTP, tipos e contexto de autenticação

**Files:**
- Create: `frontend/src/lib/jwt.ts`, `frontend/src/api/client.ts`,
  `frontend/src/api/types.ts`, `frontend/src/api/auth.ts`,
  `frontend/src/context/AuthContext.tsx`,
  `frontend/src/components/RotaProtegida.tsx`

**Interfaces:**
- Consumes: nenhuma (fundação).
- Produces: `ApiError` (classe), `apiFetch<T>(caminho, opcoes?) -> Promise<T>`,
  `decodificarJwt(token) -> PayloadToken`, `useAuth()` (hook do
  `AuthContext`, expõe `{ token, payload, empresas, carregando, login,
  logout, trocarEmpresa, recarregarEmpresas }`), `<RotaProtegida>`
  (componente).

- [ ] **Step 1: Criar `frontend/src/lib/jwt.ts`**

```typescript
export interface PayloadToken {
  sub: string;
  eh_admin_plataforma: boolean;
  empresa_id: string | null;
  papel: "admin" | "operador" | null;
  exp: number;
}

// So decodifica o payload (base64url) para uso na UI — nao verifica
// assinatura. A aplicacao da autorizacao de verdade e sempre feita pela
// API; isto e so para a SPA saber o contexto do token que ja tem.
export function decodificarJwt(token: string): PayloadToken {
  const [, payloadB64] = token.split(".");
  const normalizado = payloadB64.replace(/-/g, "+").replace(/_/g, "/");
  const json = atob(normalizado);
  return JSON.parse(json) as PayloadToken;
}
```

- [ ] **Step 2: Criar `frontend/src/api/types.ts`**

```typescript
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
```

- [ ] **Step 3: Criar `frontend/src/api/client.ts`**

```typescript
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
```

- [ ] **Step 4: Criar `frontend/src/api/auth.ts`**

```typescript
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
```

- [ ] **Step 5: Criar `frontend/src/context/AuthContext.tsx`**

```typescript
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
```

- [ ] **Step 6: Criar `frontend/src/components/RotaProtegida.tsx`**

```typescript
import { Navigate, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function RotaProtegida() {
  const { payload, carregando } = useAuth();
  if (carregando) {
    return <p>Carregando...</p>;
  }
  if (!payload) {
    return <Navigate to="/login" replace />;
  }
  return <Outlet />;
}
```

- [ ] **Step 7: Verificar o build**

```bash
cd frontend
npm run build
```

Expected: PASS — `tsc -b` não acusa erro de tipo nos arquivos novos
(nenhum deles é importado por `App.tsx` ainda, mas `tsc` verifica todo
arquivo dentro de `include`).

- [ ] **Step 8: Commit**

```bash
git add frontend/src/lib frontend/src/api frontend/src/context frontend/src/components
git commit -m "feat(frontend): client HTTP, tipos e contexto de autenticacao"
```

---

### Task 3: Login, seleção de empresa e shell de navegação

**Files:**
- Create: `frontend/src/pages/LoginPage.tsx`,
  `frontend/src/pages/SelecionarEmpresaPage.tsx`,
  `frontend/src/components/Layout.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: Task 2's `useAuth`, `RotaProtegida`, tipos de `api/types.ts`.
- Produces: rotas `/login`, `/selecionar-empresa`, shell `<Layout>`
  reutilizado por toda página autenticada a partir da Task 5.

- [ ] **Step 1: Criar `frontend/src/pages/LoginPage.tsx`**

```typescript
import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function LoginPage() {
  const { login, payload } = useAuth();
  const navegar = useNavigate();
  const [email, setEmail] = useState("");
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  if (payload) {
    return <Navigate to={payload.empresa_id ? "/emissoes" : "/selecionar-empresa"} replace />;
  }

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    setErro(null);
    setEnviando(true);
    try {
      await login(email, senha);
      navegar("/selecionar-empresa");
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Falha no login");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="cartao">
      <h1>Entrar</h1>
      <form onSubmit={enviar}>
        <div className="form-linha">
          <label htmlFor="email">E-mail</label>
          <input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="senha">Senha</label>
          <input id="senha" type="password" required value={senha} onChange={(e) => setSenha(e.target.value)} />
        </div>
        {erro && <p className="erro">{erro}</p>}
        <button type="submit" disabled={enviando}>{enviando ? "Entrando..." : "Entrar"}</button>
      </form>
      <p><a href="/aceitar-convite">Tenho um convite</a></p>
    </div>
  );
}
```

- [ ] **Step 2: Criar `frontend/src/pages/SelecionarEmpresaPage.tsx`**

```typescript
import { useNavigate } from "react-router-dom";
import { useState } from "react";
import { useAuth } from "../context/AuthContext";

export default function SelecionarEmpresaPage() {
  const { payload, empresas, trocarEmpresa } = useAuth();
  const navegar = useNavigate();
  const [erro, setErro] = useState<string | null>(null);

  if (payload?.eh_admin_plataforma) {
    return (
      <div className="cartao">
        <h1>Administrador da plataforma</h1>
        <p>
          Convites de titular e cadastro de empresa para outra pessoa ainda
          sao feitos via API por este perfil.
        </p>
      </div>
    );
  }

  async function selecionar(empresaId: string) {
    setErro(null);
    try {
      await trocarEmpresa(empresaId);
      navegar("/emissoes");
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel trocar de empresa");
    }
  }

  if (empresas.length === 0) {
    return (
      <div className="cartao">
        <h1>Nenhuma empresa cadastrada</h1>
        <p>Cadastre sua primeira empresa para comecar a emitir notas.</p>
        <button onClick={() => navegar("/cadastro-empresa")}>Cadastrar empresa</button>
      </div>
    );
  }

  return (
    <div className="cartao">
      <h1>Escolha uma empresa</h1>
      {erro && <p className="erro">{erro}</p>}
      <ul>
        {empresas.map((empresa) => (
          <li key={empresa.empresa_id}>
            <button onClick={() => selecionar(empresa.empresa_id)}>
              {empresa.cnpj} ({empresa.papel})
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
```

- [ ] **Step 3: Criar `frontend/src/components/Layout.tsx`**

```typescript
import { Link, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

export default function Layout() {
  const { payload, empresas, logout } = useAuth();
  const navegar = useNavigate();

  const empresaAtiva = empresas.find((e) => e.empresa_id === payload?.empresa_id);

  function sair() {
    logout();
    navegar("/login");
  }

  return (
    <div>
      <nav className="nav">
        <div>
          <Link to="/emissoes">Emissoes</Link>
          <Link to="/clientes">Clientes</Link>
          <Link to="/importar-csv">Importar CSV</Link>
          <Link to="/cadastro-empresa">Cadastrar empresa</Link>
        </div>
        <div>
          {empresaAtiva && (
            <>
              <span>{empresaAtiva.cnpj} </span>
              {empresas.length > 1 && (
                <button className="secundario" onClick={() => navegar("/selecionar-empresa")}>
                  Trocar empresa
                </button>
              )}
            </>
          )}
          <button className="secundario" onClick={sair}>Sair</button>
        </div>
      </nav>
      <div className="conteudo">
        <Outlet />
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Reescrever `frontend/src/App.tsx`**

```typescript
import { BrowserRouter, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./context/AuthContext";
import RotaProtegida from "./components/RotaProtegida";
import Layout from "./components/Layout";
import LoginPage from "./pages/LoginPage";
import SelecionarEmpresaPage from "./pages/SelecionarEmpresaPage";

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route element={<RotaProtegida />}>
            <Route path="/selecionar-empresa" element={<SelecionarEmpresaPage />} />
            <Route element={<Layout />}>
              <Route path="/emissoes" element={<p>Emissoes (Task 8)</p>} />
            </Route>
          </Route>
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  );
}
```

(As rotas `/cadastro-empresa`, `/clientes` e `/importar-csv` dentro de
`<Layout>` são acrescentadas nas Tasks 5, 6 e 7, respectivamente — a rota
`/emissoes` ganha sua página de verdade na Task 8.)

- [ ] **Step 5: Verificar o build**

```bash
cd frontend
npm run build
```

Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add frontend/src/pages/LoginPage.tsx frontend/src/pages/SelecionarEmpresaPage.tsx \
        frontend/src/components/Layout.tsx frontend/src/App.tsx
git commit -m "feat(frontend): login, selecao de empresa e shell de navegacao"
```

---

### Task 4: Aceitar convite

**Files:**
- Create: `frontend/src/api/convites.ts`, `frontend/src/pages/AceitarConvitePage.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: Task 2's `apiFetchJson`.
- Produces: rota pública `/aceitar-convite?token=...`.

- [ ] **Step 1: Criar `frontend/src/api/convites.ts`**

```typescript
import { apiFetchJson } from "./client";
import type { ConviteOut } from "./types";

export function aceitarConvite(token: string, senha?: string): Promise<ConviteOut> {
  return apiFetchJson<ConviteOut>("/api/convites/aceitar", "POST", { token, senha });
}
```

- [ ] **Step 2: Criar `frontend/src/pages/AceitarConvitePage.tsx`**

```typescript
import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { aceitarConvite } from "../api/convites";

export default function AceitarConvitePage() {
  const [parametros] = useSearchParams();
  const token = parametros.get("token") ?? "";
  const navegar = useNavigate();
  const [senha, setSenha] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [sucesso, setSucesso] = useState(false);
  const [enviando, setEnviando] = useState(false);

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    setErro(null);
    setEnviando(true);
    try {
      await aceitarConvite(token, senha || undefined);
      setSucesso(true);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel aceitar o convite");
    } finally {
      setEnviando(false);
    }
  }

  if (!token) {
    return <div className="cartao"><p className="erro">Link de convite invalido (sem token).</p></div>;
  }

  if (sucesso) {
    return (
      <div className="cartao">
        <h1>Convite aceito</h1>
        <button onClick={() => navegar("/login")}>Ir para o login</button>
      </div>
    );
  }

  return (
    <div className="cartao">
      <h1>Aceitar convite</h1>
      <p>
        Se voce ja tem uma conta neste sistema, deixe a senha em branco —
        so vamos vincular o acesso novo. Se e a sua primeira vez aqui,
        defina uma senha.
      </p>
      <form onSubmit={enviar}>
        <div className="form-linha">
          <label htmlFor="senha">Senha (deixe em branco se ja tiver conta)</label>
          <input id="senha" type="password" value={senha} onChange={(e) => setSenha(e.target.value)} />
        </div>
        {erro && <p className="erro">{erro}</p>}
        <button type="submit" disabled={enviando}>{enviando ? "Enviando..." : "Aceitar convite"}</button>
      </form>
    </div>
  );
}
```

- [ ] **Step 3: Acrescentar a rota em `frontend/src/App.tsx`**

```typescript
import AceitarConvitePage from "./pages/AceitarConvitePage";
```

E dentro de `<Routes>`, antes de `<Route element={<RotaProtegida />}>`:

```typescript
          <Route path="/aceitar-convite" element={<AceitarConvitePage />} />
```

- [ ] **Step 4: Verificar o build**

```bash
cd frontend
npm run build
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/convites.ts frontend/src/pages/AceitarConvitePage.tsx frontend/src/App.tsx
git commit -m "feat(frontend): tela de aceitar convite"
```

---

### Task 5: Cadastro de empresa

**Files:**
- Create: `frontend/src/api/empresas.ts`, `frontend/src/pages/CadastroEmpresaPage.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: Task 2's `apiFetch`, `ApiError`.
- Produces: rota `/cadastro-empresa` (dentro de `<Layout>`).

- [ ] **Step 1: Criar `frontend/src/api/empresas.ts`**

```typescript
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
  Object.entries(dados).forEach(([chave, valor]) => formulario.append(chave, valor));
  formulario.append("pfx", pfx);
  return apiFetch<EmpresaCriada>("/api/empresas", { method: "POST", body: formulario });
}
```

- [ ] **Step 2: Criar `frontend/src/pages/CadastroEmpresaPage.tsx`**

```typescript
import { useState, type FormEvent } from "react";
import { useAuth } from "../context/AuthContext";
import { criarEmpresa, type DadosEmpresaForm } from "../api/empresas";

const VAZIO: DadosEmpresaForm = {
  cnpj: "", inscricao_municipal: "", municipio_ibge: "", op_simp_nac: "3",
  codigo_tributacao: "", descricao_servico_padrao: "", ambiente: "homologacao",
  senha_certificado: "", titular_email: "",
};

export default function CadastroEmpresaPage() {
  const { recarregarEmpresas } = useAuth();
  const [dados, setDados] = useState<DadosEmpresaForm>(VAZIO);
  const [pfx, setPfx] = useState<File | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [sucesso, setSucesso] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  function atualizar(campo: keyof DadosEmpresaForm, valor: string) {
    setDados((atual) => ({ ...atual, [campo]: valor }));
  }

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    if (!pfx) {
      setErro("Selecione o arquivo .pfx do certificado");
      return;
    }
    setErro(null);
    setSucesso(null);
    setEnviando(true);
    try {
      const empresa = await criarEmpresa(dados, pfx);
      setSucesso(`Empresa ${empresa.cnpj} criada com sucesso.`);
      await recarregarEmpresas();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel criar a empresa");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="cartao">
      <h1>Cadastrar empresa</h1>
      <form onSubmit={enviar}>
        <div className="form-linha">
          <label htmlFor="titular_email">E-mail do titular</label>
          <input id="titular_email" required value={dados.titular_email}
            onChange={(e) => atualizar("titular_email", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="cnpj">CNPJ</label>
          <input id="cnpj" required value={dados.cnpj} onChange={(e) => atualizar("cnpj", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="im">Inscricao municipal</label>
          <input id="im" required value={dados.inscricao_municipal}
            onChange={(e) => atualizar("inscricao_municipal", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="municipio">Codigo IBGE do municipio</label>
          <input id="municipio" required value={dados.municipio_ibge}
            onChange={(e) => atualizar("municipio_ibge", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="regime">Regime (opSimpNac)</label>
          <select id="regime" value={dados.op_simp_nac} onChange={(e) => atualizar("op_simp_nac", e.target.value)}>
            <option value="1">1 - Nao optante</option>
            <option value="2">2 - Optante MEI</option>
            <option value="3">3 - Optante ME/EPP</option>
          </select>
        </div>
        <div className="form-linha">
          <label htmlFor="cod_trib">Codigo de tributacao nacional</label>
          <input id="cod_trib" required value={dados.codigo_tributacao}
            onChange={(e) => atualizar("codigo_tributacao", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="descricao">Descricao padrao do servico</label>
          <input id="descricao" required value={dados.descricao_servico_padrao}
            onChange={(e) => atualizar("descricao_servico_padrao", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="ambiente">Ambiente</label>
          <select id="ambiente" value={dados.ambiente} onChange={(e) => atualizar("ambiente", e.target.value)}>
            <option value="homologacao">Homologacao</option>
            <option value="producao">Producao</option>
          </select>
        </div>
        <div className="form-linha">
          <label htmlFor="senha_cert">Senha do certificado</label>
          <input id="senha_cert" type="password" required value={dados.senha_certificado}
            onChange={(e) => atualizar("senha_certificado", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="pfx">Certificado (.pfx)</label>
          <input id="pfx" type="file" accept=".pfx" required
            onChange={(e) => setPfx(e.target.files?.[0] ?? null)} />
        </div>
        {erro && <p className="erro">{erro}</p>}
        {sucesso && <p>{sucesso}</p>}
        <button type="submit" disabled={enviando}>{enviando ? "Enviando..." : "Cadastrar"}</button>
      </form>
    </div>
  );
}
```

- [ ] **Step 3: Acrescentar a rota em `frontend/src/App.tsx`**

```typescript
import CadastroEmpresaPage from "./pages/CadastroEmpresaPage";
```

Dentro de `<Route element={<Layout />}>`:

```typescript
              <Route path="/cadastro-empresa" element={<CadastroEmpresaPage />} />
```

- [ ] **Step 4: Verificar o build**

```bash
cd frontend
npm run build
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/empresas.ts frontend/src/pages/CadastroEmpresaPage.tsx frontend/src/App.tsx
git commit -m "feat(frontend): tela de cadastro de empresa"
```

---

### Task 6: Cadastro de clientes

**Files:**
- Create: `frontend/src/api/clientes.ts`, `frontend/src/pages/ClientesPage.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: Task 2's `apiFetch`, `apiFetchJson`, tipos `Cliente`/`ClienteForm`.
- Produces: rota `/clientes` (dentro de `<Layout>`).

- [ ] **Step 1: Criar `frontend/src/api/clientes.ts`**

```typescript
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
```

- [ ] **Step 2: Criar `frontend/src/pages/ClientesPage.tsx`**

```typescript
import { useEffect, useState, type FormEvent } from "react";
import { atualizarCliente, criarCliente, listarClientes } from "../api/clientes";
import type { Cliente, ClienteForm } from "../api/types";

const VAZIO: ClienteForm = {
  cpf_cnpj: "", nome: "", email: "", telefone: "", inscricao_estadual: "",
  inscricao_municipal: "", logradouro: "", numero: "", complemento: "",
  bairro: "", municipio_ibge: "", uf: "", cep: "",
};

function normalizar(dados: ClienteForm): ClienteForm {
  const limpo = { ...dados };
  (Object.keys(limpo) as (keyof ClienteForm)[]).forEach((chave) => {
    if (limpo[chave] === "") {
      (limpo as Record<string, string | null>)[chave] = null;
    }
  });
  return limpo;
}

export default function ClientesPage() {
  const [clientes, setClientes] = useState<Cliente[]>([]);
  const [editando, setEditando] = useState<Cliente | null>(null);
  const [form, setForm] = useState<ClienteForm>(VAZIO);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);

  async function carregar() {
    setCarregando(true);
    const lista = await listarClientes();
    setClientes(lista);
    setCarregando(false);
  }

  useEffect(() => {
    carregar();
  }, []);

  function iniciarEdicao(cliente: Cliente) {
    setEditando(cliente);
    const { id: _id, ...resto } = cliente;
    setForm(resto);
  }

  function iniciarNovo() {
    setEditando(null);
    setForm(VAZIO);
  }

  function atualizarCampo(campo: keyof ClienteForm, valor: string) {
    setForm((atual) => ({ ...atual, [campo]: valor }));
  }

  async function salvar(evento: FormEvent) {
    evento.preventDefault();
    setErro(null);
    try {
      if (editando) {
        await atualizarCliente(editando.id, { ...normalizar(form), ativo: editando.ativo });
      } else {
        await criarCliente(normalizar(form));
      }
      iniciarNovo();
      await carregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel salvar o cliente");
    }
  }

  async function alternarAtivo(cliente: Cliente) {
    const { id, ...resto } = cliente;
    await atualizarCliente(id, { ...resto, ativo: !cliente.ativo });
    await carregar();
  }

  return (
    <div>
      <h1>Clientes</h1>
      <form onSubmit={salvar} className="cartao" style={{ margin: 0, marginBottom: "1.5rem" }}>
        <h2>{editando ? `Editando ${editando.nome}` : "Novo cliente"}</h2>
        <div className="form-linha">
          <label htmlFor="nome">Nome</label>
          <input id="nome" required value={form.nome ?? ""} onChange={(e) => atualizarCampo("nome", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="cpf_cnpj">CPF/CNPJ</label>
          <input id="cpf_cnpj" value={form.cpf_cnpj ?? ""} onChange={(e) => atualizarCampo("cpf_cnpj", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="email">E-mail</label>
          <input id="email" value={form.email ?? ""} onChange={(e) => atualizarCampo("email", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="telefone">Telefone</label>
          <input id="telefone" value={form.telefone ?? ""} onChange={(e) => atualizarCampo("telefone", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="ie">Inscricao estadual</label>
          <input id="ie" value={form.inscricao_estadual ?? ""} onChange={(e) => atualizarCampo("inscricao_estadual", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="im">Inscricao municipal</label>
          <input id="im" value={form.inscricao_municipal ?? ""} onChange={(e) => atualizarCampo("inscricao_municipal", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="logradouro">Logradouro</label>
          <input id="logradouro" value={form.logradouro ?? ""} onChange={(e) => atualizarCampo("logradouro", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="numero">Numero</label>
          <input id="numero" value={form.numero ?? ""} onChange={(e) => atualizarCampo("numero", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="complemento">Complemento</label>
          <input id="complemento" value={form.complemento ?? ""} onChange={(e) => atualizarCampo("complemento", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="bairro">Bairro</label>
          <input id="bairro" value={form.bairro ?? ""} onChange={(e) => atualizarCampo("bairro", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="municipio_ibge">Codigo IBGE do municipio</label>
          <input id="municipio_ibge" value={form.municipio_ibge ?? ""} onChange={(e) => atualizarCampo("municipio_ibge", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="uf">UF</label>
          <input id="uf" maxLength={2} value={form.uf ?? ""} onChange={(e) => atualizarCampo("uf", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="cep">CEP</label>
          <input id="cep" value={form.cep ?? ""} onChange={(e) => atualizarCampo("cep", e.target.value)} />
        </div>
        {erro && <p className="erro">{erro}</p>}
        <button type="submit">{editando ? "Salvar alteracoes" : "Criar cliente"}</button>
        {editando && <button type="button" className="secundario" onClick={iniciarNovo}>Cancelar edicao</button>}
      </form>

      {carregando ? (
        <p>Carregando...</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Nome</th><th>CPF/CNPJ</th><th>E-mail</th><th>Ativo</th><th></th>
            </tr>
          </thead>
          <tbody>
            {clientes.map((cliente) => (
              <tr key={cliente.id}>
                <td>{cliente.nome}</td>
                <td>{cliente.cpf_cnpj ?? "-"}</td>
                <td>{cliente.email ?? "-"}</td>
                <td>{cliente.ativo ? "Sim" : "Nao"}</td>
                <td>
                  <button className="secundario" onClick={() => iniciarEdicao(cliente)}>Editar</button>
                  <button className={cliente.ativo ? "perigo" : ""} onClick={() => alternarAtivo(cliente)}>
                    {cliente.ativo ? "Inativar" : "Reativar"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Acrescentar a rota em `frontend/src/App.tsx`**

```typescript
import ClientesPage from "./pages/ClientesPage";
```

Dentro de `<Route element={<Layout />}>`:

```typescript
              <Route path="/clientes" element={<ClientesPage />} />
```

- [ ] **Step 4: Verificar o build**

```bash
cd frontend
npm run build
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/clientes.ts frontend/src/pages/ClientesPage.tsx frontend/src/App.tsx
git commit -m "feat(frontend): tela de cadastro de clientes"
```

---

### Task 7: Importar CSV

**Files:**
- Modify: `frontend/src/api/emissoes.ts` (criado nesta task; Task 8 acrescenta o resto)
- Create: `frontend/src/pages/ImportarCsvPage.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: Task 2's `apiFetch`.
- Produces: `previewCsv(arquivo) -> Promise<ResultadoImportacaoCsv>`,
  `confirmarCsv(arquivo) -> Promise<ResultadoImportacaoCsv>`. Rota
  `/importar-csv`.

- [ ] **Step 1: Criar `frontend/src/api/emissoes.ts`**

```typescript
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
```

- [ ] **Step 2: Criar `frontend/src/pages/ImportarCsvPage.tsx`**

```typescript
import { useState } from "react";
import { confirmarCsv, previewCsv } from "../api/emissoes";
import type { ResultadoImportacaoCsv } from "../api/types";

export default function ImportarCsvPage() {
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [preview, setPreview] = useState<ResultadoImportacaoCsv | null>(null);
  const [resultado, setResultado] = useState<ResultadoImportacaoCsv | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [processando, setProcessando] = useState(false);

  async function verPreview() {
    if (!arquivo) return;
    setErro(null);
    setResultado(null);
    setProcessando(true);
    try {
      setPreview(await previewCsv(arquivo));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel ler o arquivo");
    } finally {
      setProcessando(false);
    }
  }

  async function confirmar() {
    if (!arquivo) return;
    setErro(null);
    setProcessando(true);
    try {
      setResultado(await confirmarCsv(arquivo));
      setPreview(null);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel confirmar a importacao");
    } finally {
      setProcessando(false);
    }
  }

  return (
    <div className="cartao">
      <h1>Importar CSV da Stone</h1>
      <div className="form-linha">
        <input type="file" accept=".csv" onChange={(e) => {
          setArquivo(e.target.files?.[0] ?? null);
          setPreview(null);
          setResultado(null);
        }} />
      </div>
      <button onClick={verPreview} disabled={!arquivo || processando}>Ver previa</button>

      {erro && <p className="erro">{erro}</p>}

      {preview && (
        <div>
          <h2>Previa</h2>
          <p>{preview.total_notas} notas, total R$ {preview.valor_total}</p>
          <p>
            Ignoradas — status nao pago: {preview.ignoradas.status_nao_pago},
            categoria nao venda: {preview.ignoradas.categoria_nao_venda},
            linha invalida: {preview.ignoradas.linha_invalida},
            ja emitida: {preview.ignoradas.ja_emitida_anteriormente}
          </p>
          <button onClick={confirmar} disabled={processando}>Confirmar importacao</button>
        </div>
      )}

      {resultado && (
        <div>
          <h2>Importacao confirmada</h2>
          <p>{resultado.total_notas} notas criadas, total R$ {resultado.valor_total}</p>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Acrescentar a rota em `frontend/src/App.tsx`**

```typescript
import ImportarCsvPage from "./pages/ImportarCsvPage";
```

Dentro de `<Route element={<Layout />}>`:

```typescript
              <Route path="/importar-csv" element={<ImportarCsvPage />} />
```

- [ ] **Step 4: Verificar o build**

```bash
cd frontend
npm run build
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/emissoes.ts frontend/src/pages/ImportarCsvPage.tsx frontend/src/App.tsx
git commit -m "feat(frontend): tela de importacao de CSV"
```

---

### Task 8: Emissões — listagem, cancelamento e download

**Files:**
- Modify: `frontend/src/api/emissoes.ts`
- Create: `frontend/src/pages/EmissoesPage.tsx`
- Modify: `frontend/src/App.tsx`

**Interfaces:**
- Consumes: Task 7's `frontend/src/api/emissoes.ts` (acrescenta funções no
  mesmo arquivo).
- Produces: `listarEmissoes(filtros?) -> Promise<Emissao[]>`,
  `cancelarEmissao(id, motivo, codigoMotivo) -> Promise<Emissao>`,
  `urlXml(id)`/`urlPdf(id) -> string`. Rota `/emissoes` passa a apontar
  para a página de verdade (substitui o placeholder da Task 3).

- [ ] **Step 1: Editar `frontend/src/api/emissoes.ts`**

Trocar a linha de import de `"./client"` no topo do arquivo (hoje só
`import { apiFetch } from "./client";`, criada na Task 7) para incluir
`apiFetchJson`:

```typescript
import { apiFetch, apiFetchJson } from "./client";
import type { Emissao } from "./types";
```

Acrescentar, ao fim do arquivo (depois de `confirmarCsv`):

```typescript
export async function listarEmissoes(status?: string): Promise<Emissao[]> {
  const parametros = status ? `?status=${encodeURIComponent(status)}` : "";
  return apiFetch<Emissao[]>(`/api/emissoes${parametros}`);
}

export function cancelarEmissao(id: string, motivo: string, codigoMotivo: string): Promise<Emissao> {
  return apiFetchJson<Emissao>(`/api/emissoes/${id}/cancelar`, "POST", {
    motivo, codigo_motivo: codigoMotivo,
  });
}

export function urlXml(id: string): string {
  return `/api/emissoes/${id}/xml`;
}

export function urlPdf(id: string): string {
  return `/api/emissoes/${id}/pdf`;
}
```

- [ ] **Step 2: Criar `frontend/src/pages/EmissoesPage.tsx`**

```typescript
import { useEffect, useState } from "react";
import { cancelarEmissao, listarEmissoes, urlPdf, urlXml } from "../api/emissoes";
import { obterToken } from "../api/client";
import type { Emissao } from "../api/types";

const STATUS = ["", "pendente", "autorizada", "rejeitada", "cancelada", "cancelamento_pendente", "erro_cancelamento"];

export default function EmissoesPage() {
  const [emissoes, setEmissoes] = useState<Emissao[]>([]);
  const [filtroStatus, setFiltroStatus] = useState("");
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [cancelandoId, setCancelandoId] = useState<string | null>(null);
  const [motivo, setMotivo] = useState("");
  const [codigoMotivo, setCodigoMotivo] = useState("9");

  async function carregar() {
    setCarregando(true);
    setErro(null);
    try {
      setEmissoes(await listarEmissoes(filtroStatus || undefined));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel carregar as emissoes");
    } finally {
      setCarregando(false);
    }
  }

  useEffect(() => {
    carregar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtroStatus]);

  async function confirmarCancelamento(id: string) {
    setErro(null);
    try {
      await cancelarEmissao(id, motivo, codigoMotivo);
      setCancelandoId(null);
      setMotivo("");
      await carregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel cancelar a emissao");
    }
  }

  async function baixar(url: string, nomeArquivo: string) {
    const token = obterToken();
    const resposta = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!resposta.ok) {
      setErro("Nao foi possivel baixar o arquivo");
      return;
    }
    const blob = await resposta.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = nomeArquivo;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  return (
    <div>
      <h1>Emissoes</h1>
      <div className="form-linha" style={{ maxWidth: 240 }}>
        <label htmlFor="status">Filtrar por status</label>
        <select id="status" value={filtroStatus} onChange={(e) => setFiltroStatus(e.target.value)}>
          {STATUS.map((s) => <option key={s} value={s}>{s || "Todos"}</option>)}
        </select>
      </div>

      {erro && <p className="erro">{erro}</p>}

      {carregando ? (
        <p>Carregando...</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Numero</th><th>Origem</th><th>Status</th><th>Valor</th><th>Competencia</th><th></th>
            </tr>
          </thead>
          <tbody>
            {emissoes.map((emissao) => (
              <tr key={emissao.id}>
                <td>{emissao.serie}/{emissao.numero}</td>
                <td>{emissao.origem}</td>
                <td>{emissao.status}</td>
                <td>R$ {emissao.valor}</td>
                <td>{emissao.competencia}</td>
                <td>
                  {emissao.status === "autorizada" && (
                    <>
                      <button className="secundario" onClick={() => baixar(urlXml(emissao.id), `${emissao.chave_acesso}.xml`)}>XML</button>
                      <button className="secundario" onClick={() => baixar(urlPdf(emissao.id), `${emissao.chave_acesso}.pdf`)}>PDF</button>
                      <button className="perigo" onClick={() => setCancelandoId(emissao.id)}>Cancelar</button>
                    </>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}

      {cancelandoId && (
        <div className="cartao">
          <h2>Cancelar emissao</h2>
          <div className="form-linha">
            <label htmlFor="codigo_motivo">Motivo</label>
            <select id="codigo_motivo" value={codigoMotivo} onChange={(e) => setCodigoMotivo(e.target.value)}>
              <option value="1">Erro na emissao</option>
              <option value="2">Servico nao prestado</option>
              <option value="9">Outros</option>
            </select>
          </div>
          <div className="form-linha">
            <label htmlFor="motivo">Detalhe</label>
            <input id="motivo" required value={motivo} onChange={(e) => setMotivo(e.target.value)} />
          </div>
          <button onClick={() => confirmarCancelamento(cancelandoId)}>Confirmar cancelamento</button>
          <button className="secundario" onClick={() => setCancelandoId(null)}>Voltar</button>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 3: Atualizar a rota `/emissoes` em `frontend/src/App.tsx`**

```typescript
import EmissoesPage from "./pages/EmissoesPage";
```

Trocar `<Route path="/emissoes" element={<p>Emissoes (Task 8)</p>} />` por:

```typescript
              <Route path="/emissoes" element={<EmissoesPage />} />
```

- [ ] **Step 4: Verificar o build**

```bash
cd frontend
npm run build
```

Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add frontend/src/api/emissoes.ts frontend/src/pages/EmissoesPage.tsx frontend/src/App.tsx
git commit -m "feat(frontend): tela de emissoes com cancelamento e download"
```

---

### Task 9: Servir em produção pelo FastAPI + verificação final

**Files:**
- Modify: `app/main.py`, `README.md`

**Interfaces:**
- Produces: FastAPI serve `frontend/dist/` em `/` (com fallback de SPA)
  quando o diretório existe.

- [ ] **Step 1: Editar `app/main.py`**

```python
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from app.routers import auth, clientes, convites, dashboard, emissoes, empresas, webhook_stone

app = FastAPI(title="NFS-e Automatizada")
app.include_router(auth.router, prefix="/api")
app.include_router(convites.router, prefix="/api")
app.include_router(clientes.router, prefix="/api")
app.include_router(empresas.router, prefix="/api")
app.include_router(emissoes.router, prefix="/api")
app.include_router(webhook_stone.router, prefix="/api")
app.include_router(dashboard.router, prefix="/api")


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


_FRONTEND_DIST = Path(__file__).resolve().parent.parent / "frontend" / "dist"

if _FRONTEND_DIST.is_dir():
    app.mount("/assets", StaticFiles(directory=_FRONTEND_DIST / "assets"), name="frontend-assets")

    @app.get("/{caminho_completo:path}")
    async def servir_spa(caminho_completo: str) -> FileResponse:
        # Qualquer rota que nao seja /api, /health ou /assets cai aqui e
        # devolve o index.html — o roteamento de verdade (login, emissoes,
        # etc.) e feito pelo react-router no navegador, nao pelo backend.
        return FileResponse(_FRONTEND_DIST / "index.html")
```

Este catch-all só é registrado quando `frontend/dist/` existe (build já
rodado) — em ambiente de desenvolvimento sem build, o backend continua
funcionando normalmente só como API, sem quebrar `test_main_rotas_registradas.py`
(que roda contra o código sem depender de um build de frontend presente).

- [ ] **Step 2: Build do frontend e verificação manual via Playwright (build + preview, nunca dev server)**

```bash
cd frontend
npm run build
npm run preview &
```

Em outro terminal, com o backend já rodando (`uvicorn app.main:app` na
porta 8000) e um titular/empresa/cliente de teste já cadastrados no banco
(reaproveitar os helpers de teste ou os passos manuais do README), rodar
uma verificação pontual com Playwright CLI contra `http://localhost:4173`
(a porta do preview) exercitando o fluxo: login → seleção de empresa →
importar CSV → ver emissões → cadastro de cliente. Não commitar nenhum
script de teste — é uma checagem manual única antes de reportar a task
como pronta, consistente com a decisão da spec de não ter suíte
automatizada de frontend nesta fase. Depois de confirmado visualmente
(prints ou navegação manual), encerrar o `npm run preview` (`kill %1` ou
`Ctrl+C`).

Expected: login funciona, troca de empresa funciona quando há mais de
uma, CSV mostra prévia e confirma, lista de emissões aparece, cadastro de
cliente salva e aparece na lista.

- [ ] **Step 3: Atualizar `README.md`**

Acrescentar depois do passo 8 (worker) na seção "Rodando localmente":

```markdown
9. Frontend em dev: `cd frontend && npm install && npm run dev` — abre em
   `http://localhost:5173`, com proxy para a API em `8000`.
10. Frontend em produção: `cd frontend && npm run build` — o FastAPI passa
    a servir `frontend/dist/` automaticamente em `/` quando esse diretório
    existir (nenhuma configuração adicional).
```

- [ ] **Step 4: Rodar a suíte completa do backend uma última vez**

```bash
pytest -q
```

Expected: PASS — o `_FRONTEND_DIST.is_dir()` só é `True` se alguém já
rodou `npm run build`; se o CI/ambiente de teste não tiver isso, o
catch-all simplesmente não é registrado e nada muda para os testes
existentes. Se `frontend/dist/` **estiver** presente neste ambiente
(porque a Step 2 acabou de gerá-la), confirmar que
`test_main_rotas_registradas.py` continua passando — ele só verifica
presença/ausência das rotas de API conhecidas, não a lista completa
(nenhuma mudança nesse teste é necessária).

- [ ] **Step 5: Commit**

```bash
git add app/main.py README.md
git commit -m "feat: FastAPI serve o build do frontend em producao"
```
