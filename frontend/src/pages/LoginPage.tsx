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
