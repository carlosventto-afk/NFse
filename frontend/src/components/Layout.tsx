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
          <Link to="/numeracao">Numeracao</Link>
          <Link to="/editar-empresa">Editar empresa</Link>
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
