import { useEffect, useState, type FormEvent } from "react";
import { editarEmpresa, obterMinhaEmpresa, type DadosEdicaoEmpresa } from "../api/empresas";

const VAZIO: DadosEdicaoEmpresa = {
  cnpj: "", inscricao_municipal: "", municipio_ibge: "", local_prestacao_ibge: "",
  op_simp_nac: "3", codigo_tributacao: "", codigo_tributacao_municipal: "",
  descricao_servico_padrao: "", ambiente: "homologacao",
  senha_certificado: "",
};

export default function EditarEmpresaPage() {
  const [dados, setDados] = useState<DadosEdicaoEmpresa>(VAZIO);
  const [pfx, setPfx] = useState<File | null>(null);
  const [certificadoValidoAte, setCertificadoValidoAte] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [sucesso, setSucesso] = useState<string | null>(null);

  useEffect(() => {
    obterMinhaEmpresa()
      .then((empresa) => {
        setDados({
          cnpj: empresa.cnpj,
          inscricao_municipal: empresa.inscricao_municipal ?? "",
          municipio_ibge: empresa.municipio_ibge,
          local_prestacao_ibge: empresa.local_prestacao_ibge ?? "",
          op_simp_nac: String(empresa.op_simp_nac),
          codigo_tributacao: empresa.codigo_tributacao,
          codigo_tributacao_municipal: empresa.codigo_tributacao_municipal ?? "",
          descricao_servico_padrao: empresa.descricao_servico_padrao,
          ambiente: empresa.ambiente,
          senha_certificado: "",
        });
        setCertificadoValidoAte(empresa.certificado_valido_ate);
      })
      .catch((e) => setErro(e instanceof Error ? e.message : "Nao foi possivel carregar a empresa"))
      .finally(() => setCarregando(false));
  }, []);

  function atualizar(campo: keyof DadosEdicaoEmpresa, valor: string) {
    setDados((atual) => ({ ...atual, [campo]: valor }));
  }

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    setErro(null);
    setSucesso(null);
    setEnviando(true);
    try {
      const empresa = await editarEmpresa(dados, pfx);
      setCertificadoValidoAte(empresa.certificado_valido_ate);
      setPfx(null);
      setSucesso("Dados da empresa atualizados.");
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel salvar as alteracoes");
    } finally {
      setEnviando(false);
    }
  }

  if (carregando) {
    return <p>Carregando...</p>;
  }

  return (
    <div className="cartao">
      <h1>Editar empresa</h1>
      <form onSubmit={enviar}>
        <div className="form-linha">
          <label htmlFor="cnpj">CNPJ</label>
          <input id="cnpj" required value={dados.cnpj} onChange={(e) => atualizar("cnpj", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="im">Inscricao municipal (deixe em branco se o municipio nao exigir)</label>
          <input id="im" value={dados.inscricao_municipal}
            onChange={(e) => atualizar("inscricao_municipal", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="municipio">Codigo IBGE do municipio</label>
          <input id="municipio" required value={dados.municipio_ibge}
            onChange={(e) => atualizar("municipio_ibge", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="local_prestacao">
            Codigo IBGE do local da prestacao (deixe em branco se for o mesmo municipio acima)
          </label>
          <input id="local_prestacao" value={dados.local_prestacao_ibge}
            onChange={(e) => atualizar("local_prestacao_ibge", e.target.value)} />
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
          <label htmlFor="cod_trib_mun">
            Codigo de tributacao municipal (3 digitos — so se o municipio exigir)
          </label>
          <input id="cod_trib_mun" maxLength={3} value={dados.codigo_tributacao_municipal}
            onChange={(e) => atualizar("codigo_tributacao_municipal", e.target.value)} />
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

        <hr />
        <p>
          Certificado atual valido ate:{" "}
          {certificadoValidoAte ? new Date(certificadoValidoAte).toLocaleDateString("pt-BR") : "-"}.
          Preencha os campos abaixo somente para trocar o certificado.
        </p>
        <div className="form-linha">
          <label htmlFor="senha_cert">Senha do novo certificado</label>
          <input id="senha_cert" type="password" value={dados.senha_certificado}
            onChange={(e) => atualizar("senha_certificado", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="pfx">Novo certificado (.pfx)</label>
          <input id="pfx" type="file" accept=".pfx"
            onChange={(e) => setPfx(e.target.files?.[0] ?? null)} />
        </div>

        {erro && <p className="erro">{erro}</p>}
        {sucesso && <p>{sucesso}</p>}
        <button type="submit" disabled={enviando}>{enviando ? "Salvando..." : "Salvar"}</button>
      </form>
    </div>
  );
}
