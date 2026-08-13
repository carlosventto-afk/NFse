import { useState, type FormEvent } from "react";
import { useAuth } from "../context/AuthContext";
import { criarEmpresa, type DadosEmpresaForm } from "../api/empresas";

const VAZIO: DadosEmpresaForm = {
  cnpj: "", inscricao_municipal: "", municipio_ibge: "", op_simp_nac: "3",
  codigo_tributacao: "", descricao_servico_padrao: "", ambiente: "homologacao",
  senha_certificado: "", titular_email: "",
};

export default function CadastroEmpresaPage() {
  const { recarregarEmpresas } = useAuth();
  const [dados, setDados] = useState<DadosEmpresaForm>(VAZIO);
  const [pfx, setPfx] = useState<File | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [sucesso, setSucesso] = useState<string | null>(null);
  const [enviando, setEnviando] = useState(false);

  function atualizar(campo: keyof DadosEmpresaForm, valor: string) {
    setDados((atual) => ({ ...atual, [campo]: valor }));
  }

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    if (!pfx) {
      setErro("Selecione o arquivo .pfx do certificado");
      return;
    }
    setErro(null);
    setSucesso(null);
    setEnviando(true);
    try {
      const empresa = await criarEmpresa(dados, pfx);
      setSucesso(`Empresa ${empresa.cnpj} criada com sucesso.`);
      await recarregarEmpresas();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel criar a empresa");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="cartao">
      <h1>Cadastrar empresa</h1>
      <form onSubmit={enviar}>
        <div className="form-linha">
          <label htmlFor="titular_email">E-mail do titular</label>
          <input id="titular_email" required value={dados.titular_email}
            onChange={(e) => atualizar("titular_email", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="cnpj">CNPJ</label>
          <input id="cnpj" required value={dados.cnpj} onChange={(e) => atualizar("cnpj", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="im">Inscricao municipal</label>
          <input id="im" required value={dados.inscricao_municipal}
            onChange={(e) => atualizar("inscricao_municipal", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="municipio">Codigo IBGE do municipio</label>
          <input id="municipio" required value={dados.municipio_ibge}
            onChange={(e) => atualizar("municipio_ibge", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="regime">Regime (opSimpNac)</label>
          <select id="regime" value={dados.op_simp_nac} onChange={(e) => atualizar("op_simp_nac", e.target.value)}>
            <option value="1">1 - Nao optante</option>
            <option value="2">2 - Optante MEI</option>
            <option value="3">3 - Optante ME/EPP</option>
          </select>
        </div>
        <div className="form-linha">
          <label htmlFor="cod_trib">Codigo de tributacao nacional</label>
          <input id="cod_trib" required value={dados.codigo_tributacao}
            onChange={(e) => atualizar("codigo_tributacao", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="descricao">Descricao padrao do servico</label>
          <input id="descricao" required value={dados.descricao_servico_padrao}
            onChange={(e) => atualizar("descricao_servico_padrao", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="ambiente">Ambiente</label>
          <select id="ambiente" value={dados.ambiente} onChange={(e) => atualizar("ambiente", e.target.value)}>
            <option value="homologacao">Homologacao</option>
            <option value="producao">Producao</option>
          </select>
        </div>
        <div className="form-linha">
          <label htmlFor="senha_cert">Senha do certificado</label>
          <input id="senha_cert" type="password" required value={dados.senha_certificado}
            onChange={(e) => atualizar("senha_certificado", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="pfx">Certificado (.pfx)</label>
          <input id="pfx" type="file" accept=".pfx" required
            onChange={(e) => setPfx(e.target.files?.[0] ?? null)} />
        </div>
        {erro && <p className="erro">{erro}</p>}
        {sucesso && <p>{sucesso}</p>}
        <button type="submit" disabled={enviando}>{enviando ? "Enviando..." : "Cadastrar"}</button>
      </form>
    </div>
  );
}
