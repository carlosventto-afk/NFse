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
