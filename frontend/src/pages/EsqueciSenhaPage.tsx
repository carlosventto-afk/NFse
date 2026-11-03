import { useState, type FormEvent } from "react";
import { esqueciSenha } from "../api/auth";
import LogoVTR from "../components/LogoVTR";

export default function EsqueciSenhaPage() {
  const [email, setEmail] = useState("");
  const [erro, setErro] = useState<string | null>(null);
  const [enviado, setEnviado] = useState(false);
  const [enviando, setEnviando] = useState(false);

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    setErro(null);
    setEnviando(true);
    try {
      await esqueciSenha(email);
      setEnviado(true);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel enviar o e-mail");
    } finally {
      setEnviando(false);
    }
  }

  if (enviado) {
    return (
      <div className="tela-auth">
        <div className="cartao">
          <div className="marca-auth"><LogoVTR tamanho={26} /><span className="wordmark">VTR</span> NFS-e</div>
          <h1>Verifique seu e-mail</h1>
          <p className="ajuda">
            Se houver uma conta com o e-mail informado, enviamos um link para
            redefinir a senha. O link expira em 1 hora.
          </p>
          <p><a href="/login">Voltar para o login</a></p>
        </div>
      </div>
    );
  }

  return (
    <div className="tela-auth">
      <div className="cartao">
        <div className="marca-auth"><LogoVTR tamanho={26} /><span className="wordmark">VTR</span> NFS-e</div>
        <h1>Esqueci minha senha</h1>
        <p className="ajuda">Informe o e-mail da sua conta para receber um link de redefinicao.</p>
        <form onSubmit={enviar}>
          <div className="form-linha">
            <label htmlFor="email">E-mail</label>
            <input id="email" type="email" required value={email} onChange={(e) => setEmail(e.target.value)} />
          </div>
          {erro && <p className="erro">{erro}</p>}
          <button type="submit" disabled={enviando}>{enviando ? "Enviando..." : "Enviar link"}</button>
        </form>
        <p><a href="/login">Voltar para o login</a></p>
      </div>
    </div>
  );
}
