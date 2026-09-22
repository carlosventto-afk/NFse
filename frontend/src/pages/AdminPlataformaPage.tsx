import { useEffect, useState, type FormEvent } from "react";
import { useNavigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { listarTodasEmpresas, vincularUsuarioAEmpresa } from "../api/empresas";
import { listarPlanos } from "../api/planos";
import { convidarTitular } from "../api/convites";
import { criarUsuario } from "../api/usuarios";
import type { EmpresaResumo, Plano } from "../api/types";
import LogoVTR from "../components/LogoVTR";

export default function AdminPlataformaPage() {
  const { trocarEmpresa } = useAuth();
  const navegar = useNavigate();
  const [empresas, setEmpresas] = useState<EmpresaResumo[]>([]);
  const [planos, setPlanos] = useState<Plano[]>([]);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [planoId, setPlanoId] = useState("");

  const [emailNovo, setEmailNovo] = useState("");
  const [senhaNovo, setSenhaNovo] = useState("");
  const [criandoUsuario, setCriandoUsuario] = useState(false);
  const [usuarioCriado, setUsuarioCriado] = useState(false);

  const [emailConvite, setEmailConvite] = useState("");
  const [enviandoConvite, setEnviandoConvite] = useState(false);
  const [conviteEnviado, setConviteEnviado] = useState(false);

  const [emailVincular, setEmailVincular] = useState("");
  const [empresaIdVincular, setEmpresaIdVincular] = useState("");
  const [papelVincular, setPapelVincular] = useState("operador");
  const [vinculando, setVinculando] = useState(false);
  const [vinculoFeito, setVinculoFeito] = useState(false);

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

  async function criarUsuarioDireto(evento: FormEvent) {
    evento.preventDefault();
    setErro(null);
    setUsuarioCriado(false);
    setCriandoUsuario(true);
    try {
      await criarUsuario(emailNovo, senhaNovo, planoId);
      setUsuarioCriado(true);
      setEmailNovo("");
      setSenhaNovo("");
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel criar o usuario");
    } finally {
      setCriandoUsuario(false);
    }
  }

  async function vincular(evento: FormEvent) {
    evento.preventDefault();
    setErro(null);
    setVinculoFeito(false);
    setVinculando(true);
    try {
      await vincularUsuarioAEmpresa(empresaIdVincular, emailVincular, papelVincular);
      setVinculoFeito(true);
      setEmailVincular("");
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel vincular o usuario");
    } finally {
      setVinculando(false);
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
        <div className="marca-auth"><LogoVTR tamanho={26} /><span className="wordmark">VTR</span> NFS-e</div>
        <h1>Administração da plataforma</h1>

        {erro && <p className="erro">{erro}</p>}

        <h2>Cadastrar usuário</h2>
        <p className="ajuda">
          Cria a conta na hora, já com a senha definida — sem precisar de
          convite por e-mail.
        </p>
        <form onSubmit={criarUsuarioDireto}>
          <div className="form-linha">
            <label htmlFor="email_novo">E-mail</label>
            <input
              id="email_novo" type="email" required
              value={emailNovo} onChange={(e) => setEmailNovo(e.target.value)}
            />
          </div>
          <div className="form-linha">
            <label htmlFor="senha_novo">Senha</label>
            <input
              id="senha_novo" type="password" required minLength={8}
              value={senhaNovo} onChange={(e) => setSenhaNovo(e.target.value)}
            />
          </div>
          <div className="form-linha">
            <label htmlFor="plano_novo">Plano</label>
            <select id="plano_novo" required value={planoId} onChange={(e) => setPlanoId(e.target.value)}>
              {planos.map((p) => (
                <option key={p.id} value={p.id}>{p.nome} (até {p.limite_empresas} empresas)</option>
              ))}
            </select>
          </div>
          <button type="submit" disabled={criandoUsuario || !planoId}>
            {criandoUsuario ? "Criando..." : "Criar usuário"}
          </button>
          {usuarioCriado && <p>Usuário criado.</p>}
        </form>

        <h2>Vincular usuário a uma empresa</h2>
        <p className="ajuda">
          Dá acesso a uma empresa já cadastrada pra um usuário que já existe
          (por e-mail), sem passar por convite.
        </p>
        <form onSubmit={vincular}>
          <div className="form-linha">
            <label htmlFor="email_vincular">E-mail do usuário</label>
            <input
              id="email_vincular" type="email" required
              value={emailVincular} onChange={(e) => setEmailVincular(e.target.value)}
            />
          </div>
          <div className="form-linha">
            <label htmlFor="empresa_vincular">Empresa</label>
            <select
              id="empresa_vincular" required value={empresaIdVincular}
              onChange={(e) => setEmpresaIdVincular(e.target.value)}
            >
              <option value="">Selecione</option>
              {empresas.map((empresa) => (
                <option key={empresa.id} value={empresa.id}>
                  {empresa.cnpj}{empresa.razao_social ? ` - ${empresa.razao_social}` : ""}
                </option>
              ))}
            </select>
          </div>
          <div className="form-linha">
            <label htmlFor="papel_vincular">Papel</label>
            <select id="papel_vincular" value={papelVincular} onChange={(e) => setPapelVincular(e.target.value)}>
              <option value="admin">Admin</option>
              <option value="operador">Operador</option>
            </select>
          </div>
          <button type="submit" disabled={vinculando || !empresaIdVincular}>
            {vinculando ? "Vinculando..." : "Vincular"}
          </button>
          {vinculoFeito && <p>Usuário vinculado.</p>}
        </form>

        <h2>Convidar titular por e-mail</h2>
        <p className="ajuda">
          Alternativa: envia um convite por e-mail pra a própria pessoa
          definir a senha.
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
            <label htmlFor="plano_convite">Plano</label>
            <select id="plano_convite" required value={planoId} onChange={(e) => setPlanoId(e.target.value)}>
              {planos.map((p) => (
                <option key={p.id} value={p.id}>{p.nome} (até {p.limite_empresas} empresas)</option>
              ))}
            </select>
          </div>
          <button type="submit" className="secundario" disabled={enviandoConvite || !planoId}>
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
