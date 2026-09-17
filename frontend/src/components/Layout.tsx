import { useState } from "react";
import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

const GRUPOS_NAV = [
  {
    rotulo: "Operação",
    itens: [
      { to: "/emissoes", label: "Emissões", icone: "📄" },
      { to: "/clientes", label: "Clientes", icone: "👥" },
      { to: "/importar-csv", label: "Importar CSV", icone: "⇪" },
    ],
  },
  {
    rotulo: "Empresa",
    itens: [
      { to: "/cadastro-empresa", label: "Cadastrar empresa", icone: "🏢" },
      { to: "/editar-empresa", label: "Editar empresa", icone: "⚙" },
      { to: "/numeracao", label: "Numeração", icone: "#" },
    ],
  },
];

export default function Layout() {
  const { payload, empresas, logout } = useAuth();
  const navegar = useNavigate();
  const [menuAberto, setMenuAberto] = useState(false);

  const empresaAtiva = empresas.find((e) => e.empresa_id === payload?.empresa_id);

  function sair() {
    logout();
    navegar("/login");
  }

  return (
    <div className={`shell${menuAberto ? " menu-aberto" : ""}`}>
      <aside className="sidebar">
        <div className="marca">
          <span className="marca-simbolo">🧾</span>
          <span className="marca-nome">NFS-e</span>
        </div>
        {GRUPOS_NAV.map((grupo) => (
          <nav className="nav-grupo" key={grupo.rotulo}>
            <span className="nav-rotulo">{grupo.rotulo.toUpperCase()}</span>
            {grupo.itens.map((item) => (
              <NavLink
                key={item.to}
                to={item.to}
                className={({ isActive }) => `nav-item${isActive ? " ativo" : ""}`}
                onClick={() => setMenuAberto(false)}
              >
                <span className="icone">{item.icone}</span> {item.label}
              </NavLink>
            ))}
          </nav>
        ))}
      </aside>

      <div className="conteudo">
        <header className="topbar">
          <button className="btn-menu" onClick={() => setMenuAberto((v) => !v)} aria-label="Abrir menu">☰</button>
          <div className="topbar-conta">
            {empresaAtiva && (
              <>
                <span><span className="cnpj-rotulo">CNPJ </span><span className="cnpj">{empresaAtiva.cnpj}</span></span>
                {empresas.length > 1 && (
                  <button className="link-acao" onClick={() => navegar("/selecionar-empresa")}>
                    Trocar empresa
                  </button>
                )}
              </>
            )}
            <button className="link-acao" onClick={sair}>Sair</button>
          </div>
        </header>
        <main>
          <Outlet />
        </main>
      </div>
    </div>
  );
}
