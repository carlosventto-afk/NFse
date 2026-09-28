import { useEffect, useState, type FormEvent } from "react";
import { editarEmpresa, obterMinhaEmpresa, type DadosEdicaoEmpresa } from "../api/empresas";
import { CLASS_TRIB_IBS_CBS, CST_IBS_CBS, IND_OP_IBS_CBS } from "../lib/reformaTributaria";

const VAZIO: DadosEdicaoEmpresa = {
  cnpj: "", inscricao_municipal: "", municipio_ibge: "", local_prestacao_ibge: "",
  op_simp_nac: "3", regime_apuracao_sn: "", codigo_tributacao: "", codigo_tributacao_municipal: "",
  cnae: "", aliquota_iss: "", ibs_cbs_cst: "", ibs_cbs_classificacao: "", ibs_cbs_codigo_indicador_operacao: "",
  descricao_servico_padrao: "", ambiente: "homologacao",
  senha_certificado: "",
  provedor_emissao: "direto", razao_social: "", logradouro: "", numero: "", complemento: "", bairro: "", cep: "",
};

export default function EditarEmpresaPage() {
  const [dados, setDados] = useState<DadosEdicaoEmpresa>(VAZIO);
  const [pfx, setPfx] = useState<File | null>(null);
  const [certificadoValidoAte, setCertificadoValidoAte] = useState<string | null>(null);
  const [spedyEmpresaId, setSpedyEmpresaId] = useState<string | null>(null);
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
          regime_apuracao_sn: empresa.regime_apuracao_sn != null ? String(empresa.regime_apuracao_sn) : "",
          codigo_tributacao: empresa.codigo_tributacao,
          codigo_tributacao_municipal: empresa.codigo_tributacao_municipal ?? "",
          cnae: empresa.cnae ?? "",
          aliquota_iss: empresa.aliquota_iss != null ? String(empresa.aliquota_iss) : "",
          ibs_cbs_cst: empresa.ibs_cbs_cst != null ? String(empresa.ibs_cbs_cst) : "",
          ibs_cbs_classificacao: empresa.ibs_cbs_classificacao != null ? String(empresa.ibs_cbs_classificacao) : "",
          ibs_cbs_codigo_indicador_operacao: empresa.ibs_cbs_codigo_indicador_operacao ?? "",
          descricao_servico_padrao: empresa.descricao_servico_padrao,
          ambiente: empresa.ambiente,
          senha_certificado: "",
          provedor_emissao: empresa.provedor_emissao,
          razao_social: empresa.razao_social ?? "",
          logradouro: empresa.logradouro ?? "",
          numero: empresa.numero ?? "",
          complemento: empresa.complemento ?? "",
          bairro: empresa.bairro ?? "",
          cep: empresa.cep ?? "",
        });
        setCertificadoValidoAte(empresa.certificado_valido_ate);
        setSpedyEmpresaId(empresa.spedy_empresa_id);
      })
      .catch((e) => setErro(e instanceof Error ? e.message : "Nao foi possivel carregar a empresa"))
      .finally(() => setCarregando(false));
  }, []);

  function atualizar(campo: keyof DadosEdicaoEmpresa, valor: string) {
    setDados((atual) => ({ ...atual, [campo]: valor }));
  }

  function atualizarCstIbsCbs(valor: string) {
    // Troca de CST invalida a classificacao tributaria escolhida antes (os 6
    // digitos de ibs_cbs_classificacao sempre comecam com o CST pai).
    setDados((atual) => ({ ...atual, ibs_cbs_cst: valor, ibs_cbs_classificacao: "" }));
  }

  const classificacoesDoCst = CLASS_TRIB_IBS_CBS.filter((c) => c.cst === dados.ibs_cbs_cst);

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    setErro(null);
    setSucesso(null);
    setEnviando(true);
    try {
      const empresa = await editarEmpresa(dados, pfx);
      setCertificadoValidoAte(empresa.certificado_valido_ate);
      setSpedyEmpresaId(empresa.spedy_empresa_id);
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
        {dados.op_simp_nac === "3" && (
          <div className="form-linha">
            <label htmlFor="regime_apuracao">Regime de apuracao do Simples Nacional</label>
            <select id="regime_apuracao" value={dados.regime_apuracao_sn}
              onChange={(e) => atualizar("regime_apuracao_sn", e.target.value)}>
              <option value="">Nao informar (padrao — municipio pode exigir)</option>
              <option value="1">1 - Tributos federais e municipal apurados pelo SN</option>
              <option value="2">2 - Federais pelo SN, ISSQN por fora do SN</option>
              <option value="3">3 - Federais e municipal por fora do SN</option>
            </select>
          </div>
        )}
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
          <label htmlFor="cnae">
            CNAE (so digitos — alguns municipios, como Belem, exigem pra emitir)
          </label>
          <input id="cnae" maxLength={10} value={dados.cnae}
            onChange={(e) => atualizar("cnae", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="aliquota_iss">
            Aliquota de ISS em % (opcional — usada no payload da Spedy)
          </label>
          <input id="aliquota_iss" inputMode="decimal" value={dados.aliquota_iss}
            onChange={(e) => atualizar("aliquota_iss", e.target.value)} />
        </div>
        <p className="ajuda">
          Reforma tributaria (IBS/CBS) — opcional. Tabela oficial (Portal Nacional da NFS-e,
          Informe Tecnico 2025.002 e Anexo VII). A opcao certa depende do regime da empresa —
          confirme com o contador antes de escolher; sem os 3 campos abaixo, nada e enviado.
        </p>
        <div className="form-linha">
          <label htmlFor="ibs_cbs_cst">CST do IBS/CBS</label>
          <select id="ibs_cbs_cst" value={dados.ibs_cbs_cst}
            onChange={(e) => atualizarCstIbsCbs(e.target.value)}>
            <option value="">Nao informar</option>
            {CST_IBS_CBS.map((c) => (
              <option key={c.codigo} value={c.codigo}>{c.codigo} - {c.nome}</option>
            ))}
          </select>
        </div>
        <div className="form-linha">
          <label htmlFor="ibs_cbs_classificacao">Codigo de classificacao tributaria do IBS/CBS</label>
          <select id="ibs_cbs_classificacao" value={dados.ibs_cbs_classificacao} disabled={!dados.ibs_cbs_cst}
            onChange={(e) => atualizar("ibs_cbs_classificacao", e.target.value)}>
            <option value="">{dados.ibs_cbs_cst ? "Nao informar" : "Escolha o CST primeiro"}</option>
            {classificacoesDoCst.map((c) => (
              <option key={c.codigo} value={c.codigo}>{c.codigo} - {c.nome}</option>
            ))}
          </select>
        </div>
        <div className="form-linha">
          <label htmlFor="ibs_cbs_codigo_indicador_operacao">Codigo indicador da operacao (IBS/CBS)</label>
          <select id="ibs_cbs_codigo_indicador_operacao" value={dados.ibs_cbs_codigo_indicador_operacao}
            onChange={(e) => atualizar("ibs_cbs_codigo_indicador_operacao", e.target.value)}>
            <option value="">Nao informar</option>
            {IND_OP_IBS_CBS.map((i) => (
              <option key={i.codigo} value={i.codigo}>{i.codigo} - {i.caracteristica}</option>
            ))}
          </select>
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
        <div className="form-linha">
          <label htmlFor="provedor_emissao">Provedor de emissao</label>
          <select id="provedor_emissao" value={dados.provedor_emissao}
            onChange={(e) => atualizar("provedor_emissao", e.target.value)}>
            <option value="direto">Direto (auto -- usa endpoint proprio do municipio quando existir)</option>
            <option value="nacional">NFS-e Nacional (forca o endpoint nacional generico)</option>
            <option value="spedy">Spedy</option>
          </select>
        </div>
        {dados.provedor_emissao === "spedy" && (
          <>
            <p className="ajuda">
              {spedyEmpresaId
                ? `Ja provisionada na Spedy (ID: ${spedyEmpresaId}).`
                : "Ainda nao provisionada — sera provisionada na Spedy ao salvar."}
              {" "}Trocar certificado ou ambiente depois de provisionada exige reconfigurar o provedor manualmente.
            </p>
            <div className="form-linha">
              <label htmlFor="razao_social">Razao social</label>
              <input id="razao_social" required value={dados.razao_social}
                onChange={(e) => atualizar("razao_social", e.target.value)} />
            </div>
            <div className="form-linha">
              <label htmlFor="logradouro">Logradouro</label>
              <input id="logradouro" value={dados.logradouro}
                onChange={(e) => atualizar("logradouro", e.target.value)} />
            </div>
            <div className="form-linha">
              <label htmlFor="numero">Numero</label>
              <input id="numero" value={dados.numero}
                onChange={(e) => atualizar("numero", e.target.value)} />
            </div>
            <div className="form-linha">
              <label htmlFor="complemento">Complemento</label>
              <input id="complemento" value={dados.complemento}
                onChange={(e) => atualizar("complemento", e.target.value)} />
            </div>
            <div className="form-linha">
              <label htmlFor="bairro">Bairro</label>
              <input id="bairro" value={dados.bairro}
                onChange={(e) => atualizar("bairro", e.target.value)} />
            </div>
            <div className="form-linha">
              <label htmlFor="cep">CEP</label>
              <input id="cep" maxLength={8} value={dados.cep}
                onChange={(e) => atualizar("cep", e.target.value)} />
            </div>
          </>
        )}
        <p className="ajuda">
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
