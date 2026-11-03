import { useState, type FormEvent } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { redefinirSenha } from "../api/auth";
import LogoVTR from "../components/LogoVTR";

export default function RedefinirSenhaPage() {
  const [parametros] = useSearchParams();
  const token = parametros.get("token") ?? "";
  const navegar = useNavigate();
  const [senha, setSenha] = useState("");
  const [confirmacao, setConfirmacao] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [sucesso, setSucesso] = useState(false);
  const [enviando, setEnviando] = useState(false);

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    setErro(null);
    if (senha !== confirmacao) {
      setErro("As senhas nao coincidem");
      return;
    }
    setEnviando(true);
    try {
      await redefinirSenha(token, senha);
      setSucesso(true);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel redefinir a senha");
    } finally {
      setEnviando(false);
    }
  }

  if (!token) {
    return (
      <div className="tela-auth">
        <div className="cartao"><p className="erro">Link de redefinicao invalido (sem token).</p></div>
      </div>
    );
  }

  if (sucesso) {
    return (
      <div className="tela-auth">
        <div className="cartao">
          <div className="marca-auth"><LogoVTR tamanho={26} /><span className="wordmark">VTR</span> NFS-e</div>
          <h1>Senha redefinida</h1>
          <button onClick={() => navegar("/login")}>Ir para o login</button>
        </div>
      </div>
    );
  }

  return (
    <div className="tela-auth">
      <div className="cartao">
        <div className="marca-auth"><LogoVTR tamanho={26} /><span className="wordmark">VTR</span> NFS-e</div>
        <h1>Redefinir senha</h1>
        <form onSubmit={enviar}>
          <div className="form-linha">
            <label htmlFor="senha">Nova senha</label>
            <input
              id="senha" type="password" required minLength={8}
              value={senha} onChange={(e) => setSenha(e.target.value)}
            />
          </div>
          <div className="form-linha">
            <label htmlFor="confirmacao">Confirmar nova senha</label>
            <input
              id="confirmacao" type="password" required minLength={8}
              value={confirmacao} onChange={(e) => setConfirmacao(e.target.value)}
            />
          </div>
          {erro && <p className="erro">{erro}</p>}
          <button type="submit" disabled={enviando}>{enviando ? "Salvando..." : "Redefinir senha"}</button>
        </form>
      </div>
    </div>
  );
}
