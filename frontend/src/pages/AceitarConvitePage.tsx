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
