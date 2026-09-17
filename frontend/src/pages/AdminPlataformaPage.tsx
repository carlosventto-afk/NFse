import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { listarTodasEmpresas } from "../api/empresas";
import { listarPlanos } from "../api/planos";
import { convidarTitular } from "../api/convites";
import type { EmpresaResumo, Plano } from "../api/types";

export default function AdminPlataformaPage() {
  const { trocarEmpresa } = useAuth();
  const navegar = useNavigate();
  const [empresas, setEmpresas] = useState<EmpresaResumo[]>([]);
  const [planos, setPlanos] = useState<Plano[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [emailConvite, setEmailConvite] = useState("");
  const [planoId, setPlanoId] = useState("");
  const [enviandoConvite, setEnviandoConvite] = useState(false);
  const [conviteEnviado, setConviteEnviado] = useState(false);

  useEffect(() => {
    Promise.all([listarTodasEmpresas(), listarPlanos()])
      .then(([listaEmpresas, listaPlanos]) => {
        setEmpresas(listaEmpresas);
        setPlanos(listaPlanos);
        if (listaPlanos.length > 0) {
          setPlanoId(listaPlanos[0].id);
        }
      })
      .catch((e) => setErro(e instanceof Error ? e.message : "Nao foi possivel carregar a administracao"))
      .finally(() => setCarregando(false));
  }, []);

  async function entrar(empresaId: string) {
    setErro(null);
    try {
      await trocarEmpresa(empresaId);
      navegar("/emissoes");
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel entrar nessa empresa");
    }
  }

  async function enviarConvite(evento: FormEvent) {
    evento.preventDefault();
    setErro(null);
    setConviteEnviado(false);
    setEnviandoConvite(true);
    try {
      await convidarTitular(emailConvite, planoId);
      setConviteEnviado(true);
      setEmailConvite("");
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel enviar o convite");
    } finally {
      setEnviandoConvite(false);
    }
  }

  if (carregando) {
    return <p>Carregando...</p>;
  }

  return (
    <div className="tela-auth">
      <div className="cartao" style={{ maxWidth: 720 }}>
        <div className="marca-auth"><span className="simbolo">🧾</span> NFS-e</div>
        <h1>Administração da plataforma</h1>

        {erro && <p className="erro">{erro}</p>}

        <h2>Convidar titular</h2>
        <p className="ajuda">
          Envia um convite por e-mail pra criar uma conta nova, com o plano
          escolhido, que depois cadastra a própria empresa.
        </p>
        <form onSubmit={enviarConvite}>
          <div className="form-linha">
            <label htmlFor="email_convite">E-mail</label>
            <input
              id="email_convite" type="email" required
              value={emailConvite} onChange={(e) => setEmailConvite(e.target.value)}
            />
          </div>
          <div className="form-linha">
            <label htmlFor="plano">Plano</label>
            <select id="plano" required value={planoId} onChange={(e) => setPlanoId(e.target.value)}>
              {planos.map((p) => (
                <option key={p.id} value={p.id}>{p.nome} (até {p.limite_empresas} empresas)</option>
              ))}
            </select>
          </div>
          <button type="submit" disabled={enviandoConvite || !planoId}>
            {enviandoConvite ? "Enviando..." : "Enviar convite"}
          </button>
          {conviteEnviado && <p>Convite enviado.</p>}
        </form>

        <h2>Empresas cadastradas</h2>
        <div className="painel-tabela">
          <div className="rolagem-tabela">
            <table>
              <thead>
                <tr><th>CNPJ</th><th>Razão social</th><th></th></tr>
              </thead>
              <tbody>
                {empresas.map((empresa) => (
                  <tr key={empresa.id}>
                    <td className="num">{empresa.cnpj}</td>
                    <td>{empresa.razao_social ?? "-"}</td>
                    <td><button className="secundario" onClick={() => entrar(empresa.id)}>Entrar</button></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
}
