import { useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { emitirManual, type DadosEmissaoManual } from "../api/emissoes";

const VAZIO: DadosEmissaoManual = {
  cpf_cnpj: "", nome: "", email: "", descricao: "", valor: "", competencia: "",
};

export default function EmissaoAvulsaPage() {
  const [dados, setDados] = useState<DadosEmissaoManual>(VAZIO);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [sucesso, setSucesso] = useState<string | null>(null);

  function atualizar(campo: keyof DadosEmissaoManual, valor: string) {
    setDados((atual) => ({ ...atual, [campo]: valor }));
  }

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    setErro(null);
    setSucesso(null);
    setEnviando(true);
    try {
      const emissao = await emitirManual(dados);
      setSucesso(`Nota ${emissao.serie}/${emissao.numero} criada e enviada para emissão.`);
      // Mantem competencia (comum emitir varias notas seguidas na mesma
      // competencia) e zera o resto -- fluxo pensado pra digitar nota apos
      // nota sem reabrir a tela.
      setDados((atual) => ({ ...VAZIO, competencia: atual.competencia }));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel criar a emissao");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="cartao">
      <h1>Emissão avulsa</h1>
      <p className="ajuda">
        Alternativa à importação de planilha — para empresas que não vendem por esse fluxo.
        A nota entra na fila normal de emissão (mesma usada pelo resto do sistema); acompanhe
        o status em <Link to="/emissoes">Emissões</Link>.
      </p>
      <form onSubmit={enviar}>
        <div className="form-linha">
          <label htmlFor="nome">Nome do tomador (opcional)</label>
          <input id="nome" value={dados.nome} onChange={(e) => atualizar("nome", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="cpf_cnpj">CPF/CNPJ do tomador (opcional)</label>
          <input id="cpf_cnpj" value={dados.cpf_cnpj} onChange={(e) => atualizar("cpf_cnpj", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="email">E-mail do tomador (opcional)</label>
          <input
            id="email" type="email" value={dados.email}
            onChange={(e) => atualizar("email", e.target.value)}
          />
        </div>
        <div className="form-linha">
          <label htmlFor="descricao">Descrição do serviço</label>
          <input
            id="descricao" required value={dados.descricao}
            onChange={(e) => atualizar("descricao", e.target.value)}
          />
        </div>
        <div className="form-linha">
          <label htmlFor="valor">Valor (R$)</label>
          <input
            id="valor" required inputMode="decimal" value={dados.valor}
            onChange={(e) => atualizar("valor", e.target.value)}
          />
        </div>
        <div className="form-linha">
          <label htmlFor="competencia">Competência</label>
          <input
            id="competencia" type="date" required value={dados.competencia}
            onChange={(e) => atualizar("competencia", e.target.value)}
          />
        </div>
        {erro && <p className="erro">{erro}</p>}
        {sucesso && <p>{sucesso}</p>}
        <button type="submit" disabled={enviando}>{enviando ? "Enviando..." : "Emitir"}</button>
      </form>
    </div>
  );
}
