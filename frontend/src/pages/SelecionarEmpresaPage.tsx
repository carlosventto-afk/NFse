import { useNavigate } from "react-router-dom";
import { useState } from "react";
import { useAuth } from "../context/AuthContext";
import LogoVTR from "../components/LogoVTR";

export default function SelecionarEmpresaPage() {
  const { payload, empresas, trocarEmpresa } = useAuth();
  const navegar = useNavigate();
  const [erro, setErro] = useState<string | null>(null);

  if (payload?.eh_admin_plataforma) {
    return (
      <div className="tela-auth">
        <div className="cartao">
          <div className="marca-auth"><LogoVTR tamanho={26} /><span className="wordmark">VTR</span> NFS-e</div>
          <h1>Administrador da plataforma</h1>
          <p className="ajuda">
            Acesso total: entre em qualquer empresa cadastrada ou convide um
            novo titular.
          </p>
          <button onClick={() => navegar("/admin-plataforma")}>Administrar plataforma</button>
        </div>
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
      <div className="tela-auth">
        <div className="cartao">
          <div className="marca-auth"><LogoVTR tamanho={26} /><span className="wordmark">VTR</span> NFS-e</div>
          <h1>Nenhuma empresa cadastrada</h1>
          <p className="ajuda">Cadastre sua primeira empresa para comecar a emitir notas.</p>
          <button onClick={() => navegar("/cadastro-empresa")}>Cadastrar empresa</button>
        </div>
      </div>
    );
  }

  return (
    <div className="tela-auth">
      <div className="cartao">
        <div className="marca-auth"><LogoVTR tamanho={26} /><span className="wordmark">VTR</span> NFS-e</div>
        <h1>Escolha uma empresa</h1>
        {erro && <p className="erro">{erro}</p>}
        <ul className="lista-empresas">
          {empresas.map((empresa) => (
            <li key={empresa.empresa_id}>
              <button className="secundario" onClick={() => selecionar(empresa.empresa_id)}>
                {empresa.cnpj} ({empresa.papel})
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
