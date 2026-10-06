import { useEffect, useState, type FormEvent } from "react";
import {
  definirNumeracao, editarEmpresa, obterMinhaEmpresa, obterNumeracao, type DadosEdicaoEmpresa,
} from "../api/empresas";
import { CLASS_TRIB_IBS_CBS, CST_IBS_CBS, IND_OP_IBS_CBS } from "../lib/reformaTributaria";

const VAZIO: DadosEdicaoEmpresa = {
  cnpj: "", inscricao_municipal: "", municipio_ibge: "", local_prestacao_ibge: "",
  op_simp_nac: "3", regime_apuracao_sn: "", codigo_tributacao: "", codigo_tributacao_municipal: "",
  cnae: "", nbs_code: "", aliquota_iss: "", ibs_cbs_cst: "", ibs_cbs_classificacao: "", ibs_cbs_codigo_indicador_operacao: "",
  descricao_servico_padrao: "", ambiente: "homologacao",
  senha_certificado: "",
  provedor_emissao: "direto", razao_social: "", logradouro: "", numero: "", complemento: "", bairro: "", cep: "",
};

export default function EditarEmpresaPage() {
  const [dados, setDados] = useState<DadosEdicaoEmpresa>(VAZIO);
  const [serie, setSerie] = useState("");
  const [proximoNumero, setProximoNumero] = useState("");
  const [pfx, setPfx] = useState<File | null>(null);
  const [forcarReprovisionamento, setForcarReprovisionamento] = useState(false);
  const [certificadoValidoAte, setCertificadoValidoAte] = useState<string | null>(null);
  const [spedyEmpresaId, setSpedyEmpresaId] = useState<string | null>(null);
  const [reformaAberta, setReformaAberta] = useState(false);
  const [carregando, setCarregando] = useState(true);
  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [sucesso, setSucesso] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([obterMinhaEmpresa(), obterNumeracao()])
      .then(([empresa, numeracao]) => {
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
          nbs_code: empresa.nbs_code ?? "",
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
        setReformaAberta(Boolean(empresa.ibs_cbs_cst));
        setSerie(numeracao.serie);
        setProximoNumero(String(numeracao.proximo_numero));
      })
      .catch((e) => setErro(e instanceof Error ? e.message : "Não foi possível carregar a empresa"))
      .finally(() => setCarregando(false));
  }, []);

  function atualizar(campo: keyof DadosEdicaoEmpresa, valor: string) {
    setDados((atual) => ({ ...atual, [campo]: valor }));
  }

  function atualizarCstIbsCbs(valor: string) {
    // Troca de CST invalida a classificação tributária escolhida antes (os 6
    // dígitos de ibs_cbs_classificacao sempre começam com o CST pai).
    setDados((atual) => ({ ...atual, ibs_cbs_cst: valor, ibs_cbs_classificacao: "" }));
  }

  const classificacoesDoCst = CLASS_TRIB_IBS_CBS.filter((c) => c.cst === dados.ibs_cbs_cst);

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    setErro(null);
    setSucesso(null);
    setEnviando(true);
    try {
      const empresa = await editarEmpresa(dados, pfx, forcarReprovisionamento);
      setCertificadoValidoAte(empresa.certificado_valido_ate);
      setSpedyEmpresaId(empresa.spedy_empresa_id);
      setPfx(null);
      const reprovisionou = forcarReprovisionamento;
      setForcarReprovisionamento(false);

      try {
        const numeracao = await definirNumeracao({ serie, proximo_numero: Number(proximoNumero) });
        setSerie(numeracao.serie);
        setProximoNumero(String(numeracao.proximo_numero));
        setSucesso(
          reprovisionou
            ? "Empresa reprovisionada na Spedy com uma chave nova, e numeração atualizada."
            : "Configurações salvas.",
        );
      } catch (eNumeracao) {
        setErro(
          "Os dados da empresa foram salvos, mas a numeração não pôde ser atualizada: "
          + (eNumeracao instanceof Error ? eNumeracao.message : "erro desconhecido"),
        );
      }
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível salvar as alterações");
    } finally {
      setEnviando(false);
    }
  }

  if (carregando) {
    return <p>Carregando...</p>;
  }

  return (
    <div className="pagina-config">
      <h1>Configurações da empresa</h1>
      <p className="ajuda">
        Dados fiscais, numeração das notas e o provedor usado para emitir. Tudo salva junto, de uma vez.
      </p>
      <form onSubmit={enviar}>
        <section className="secao-config">
          <h2>Identificação</h2>
          <p className="ajuda">Quem é a empresa perante a prefeitura e o sistema de notas.</p>
          <div className="grade-campos">
            <div className="form-linha">
              <label htmlFor="cnpj">CNPJ</label>
              <input id="cnpj" required value={dados.cnpj} onChange={(e) => atualizar("cnpj", e.target.value)} />
            </div>
            <div className="form-linha">
              <label htmlFor="im">Inscrição municipal</label>
              <input id="im" placeholder="Deixe em branco se o município não exigir" value={dados.inscricao_municipal}
                onChange={(e) => atualizar("inscricao_municipal", e.target.value)} />
            </div>
            <div className="form-linha">
              <label htmlFor="municipio">Código IBGE do município</label>
              <input id="municipio" required value={dados.municipio_ibge}
                onChange={(e) => atualizar("municipio_ibge", e.target.value)} />
            </div>
            <div className="form-linha">
              <label htmlFor="local_prestacao">Código IBGE do local da prestação</label>
              <input id="local_prestacao" placeholder="Deixe em branco se for o mesmo município acima"
                value={dados.local_prestacao_ibge}
                onChange={(e) => atualizar("local_prestacao_ibge", e.target.value)} />
            </div>
            <div className="form-linha campo-largo">
              <label htmlFor="descricao">Descrição padrão do serviço</label>
              <input id="descricao" required value={dados.descricao_servico_padrao}
                onChange={(e) => atualizar("descricao_servico_padrao", e.target.value)} />
            </div>
          </div>
        </section>

        <section className="secao-config">
          <h2>Tributação</h2>
          <p className="ajuda">Como o serviço desta empresa é classificado e tributado.</p>
          <div className="grade-campos">
            <div className="form-linha">
              <label htmlFor="regime">Regime tributário</label>
              <select id="regime" value={dados.op_simp_nac} onChange={(e) => atualizar("op_simp_nac", e.target.value)}>
                <option value="1">Não optante</option>
                <option value="2">Optante MEI</option>
                <option value="3">Optante ME/EPP</option>
              </select>
            </div>
            {dados.op_simp_nac === "3" && (
              <div className="form-linha">
                <label htmlFor="regime_apuracao">Regime de apuração do Simples Nacional</label>
                <select id="regime_apuracao" value={dados.regime_apuracao_sn}
                  onChange={(e) => atualizar("regime_apuracao_sn", e.target.value)}>
                  <option value="">Não informar (padrão — município pode exigir)</option>
                  <option value="1">Tributos federais e municipal apurados pelo SN</option>
                  <option value="2">Federais pelo SN, ISSQN por fora do SN</option>
                  <option value="3">Federais e municipal por fora do SN</option>
                </select>
              </div>
            )}
            <div className="form-linha">
              <label htmlFor="cod_trib">Código de tributação nacional</label>
              <input id="cod_trib" required value={dados.codigo_tributacao}
                onChange={(e) => atualizar("codigo_tributacao", e.target.value)} />
            </div>
            <div className="form-linha">
              <label htmlFor="cod_trib_mun">Código de tributação municipal</label>
              <input id="cod_trib_mun" maxLength={3} placeholder="3 dígitos — só se o município exigir"
                value={dados.codigo_tributacao_municipal}
                onChange={(e) => atualizar("codigo_tributacao_municipal", e.target.value)} />
            </div>
            <div className="form-linha">
              <label htmlFor="cnae">CNAE</label>
              <input id="cnae" maxLength={10} placeholder="Só dígitos — Belém, por exemplo, exige pra emitir"
                value={dados.cnae}
                onChange={(e) => atualizar("cnae", e.target.value)} />
            </div>
            <div className="form-linha">
              <label htmlFor="nbs_code">Código NBS</label>
              <input id="nbs_code" maxLength={20} placeholder="Formato X.XXXX.XX.XX"
                value={dados.nbs_code}
                onChange={(e) => atualizar("nbs_code", e.target.value)} />
            </div>
            <div className="form-linha">
              <label htmlFor="aliquota_iss">Alíquota de ISS (%)</label>
              <input id="aliquota_iss" inputMode="decimal" placeholder="Opcional"
                value={dados.aliquota_iss}
                onChange={(e) => atualizar("aliquota_iss", e.target.value)} />
            </div>
          </div>
        </section>

        <details className="secao-config" open={reformaAberta} onToggle={(e) => setReformaAberta(e.currentTarget.open)}>
          <summary>
            <span className="resumo-secao">
              <h2>Reforma tributária (IBS/CBS)</h2>
              <span className="ajuda">Opcional — confirme com o contador antes de preencher</span>
            </span>
            <span className="seta">▾</span>
          </summary>
          <p className="ajuda">
            Tabela oficial (Portal Nacional da NFS-e, Informe Técnico 2025.002 e Anexo VII). Sem os três
            campos preenchidos juntos, nada é enviado.
          </p>
          <div className="grade-campos">
            <div className="form-linha">
              <label htmlFor="ibs_cbs_cst">CST do IBS/CBS</label>
              <select id="ibs_cbs_cst" value={dados.ibs_cbs_cst}
                onChange={(e) => atualizarCstIbsCbs(e.target.value)}>
                <option value="">Não informar</option>
                {CST_IBS_CBS.map((c) => (
                  <option key={c.codigo} value={c.codigo}>{c.codigo} - {c.nome}</option>
                ))}
              </select>
            </div>
            <div className="form-linha">
              <label htmlFor="ibs_cbs_classificacao">Classificação tributária</label>
              <select id="ibs_cbs_classificacao" value={dados.ibs_cbs_classificacao} disabled={!dados.ibs_cbs_cst}
                onChange={(e) => atualizar("ibs_cbs_classificacao", e.target.value)}>
                <option value="">{dados.ibs_cbs_cst ? "Não informar" : "Escolha o CST primeiro"}</option>
                {classificacoesDoCst.map((c) => (
                  <option key={c.codigo} value={c.codigo}>{c.codigo} - {c.nome}</option>
                ))}
              </select>
            </div>
            <div className="form-linha campo-largo">
              <label htmlFor="ibs_cbs_codigo_indicador_operacao">Código indicador da operação</label>
              <select id="ibs_cbs_codigo_indicador_operacao" value={dados.ibs_cbs_codigo_indicador_operacao}
                onChange={(e) => atualizar("ibs_cbs_codigo_indicador_operacao", e.target.value)}>
                <option value="">Não informar</option>
                {IND_OP_IBS_CBS.map((i) => (
                  <option key={i.codigo} value={i.codigo}>{i.codigo} - {i.caracteristica}</option>
                ))}
              </select>
            </div>
          </div>
        </details>

        <section className="secao-config">
          <h2>Emissão e numeração</h2>
          <p className="ajuda">Ambiente de testes ou real, e a série/número da próxima nota.</p>
          <div className="grade-campos">
            <div className="form-linha">
              <label htmlFor="ambiente">Ambiente</label>
              <select id="ambiente" value={dados.ambiente} onChange={(e) => atualizar("ambiente", e.target.value)}>
                <option value="homologacao">Homologação (testes)</option>
                <option value="producao">Produção</option>
              </select>
            </div>
            <div className="form-linha">
              <label htmlFor="serie">Série</label>
              <input id="serie" required maxLength={5} value={serie} onChange={(e) => setSerie(e.target.value)} />
            </div>
            <div className="form-linha">
              <label htmlFor="proximo_numero">Próximo número</label>
              <input
                id="proximo_numero" type="number" min={1} required
                value={proximoNumero} onChange={(e) => setProximoNumero(e.target.value)}
              />
            </div>
          </div>
        </section>

        <section className="secao-config">
          <h2>Provedor de emissão</h2>
          <p className="ajuda">Quem conversa com a prefeitura em nome desta empresa.</p>
          <div className="grade-campos">
            <div className="form-linha campo-largo">
              <label htmlFor="provedor_emissao">Provedor</label>
              <select id="provedor_emissao" value={dados.provedor_emissao}
                onChange={(e) => atualizar("provedor_emissao", e.target.value)}>
                <option value="direto">Direto (auto — usa o endpoint próprio do município quando existir)</option>
                <option value="nacional">NFS-e Nacional (força o endpoint nacional genérico)</option>
                <option value="spedy">Spedy</option>
              </select>
            </div>
          </div>
          {dados.provedor_emissao === "spedy" && (
            <div className="subsecao-config">
              <h3>Dados cadastrais na Spedy</h3>
              <p className="ajuda">
                {spedyEmpresaId
                  ? `Já provisionada na Spedy (ID: ${spedyEmpresaId}).`
                  : "Ainda não provisionada — será provisionada na Spedy ao salvar."}
                {" "}Trocar certificado ou ambiente depois de provisionada exige reconfigurar o provedor manualmente.
              </p>
              <div className="grade-campos">
                <div className="form-linha campo-largo">
                  <label htmlFor="razao_social">Razão social</label>
                  <input id="razao_social" required value={dados.razao_social}
                    onChange={(e) => atualizar("razao_social", e.target.value)} />
                </div>
                <div className="form-linha">
                  <label htmlFor="logradouro">Logradouro</label>
                  <input id="logradouro" value={dados.logradouro}
                    onChange={(e) => atualizar("logradouro", e.target.value)} />
                </div>
                <div className="form-linha">
                  <label htmlFor="numero_end">Número</label>
                  <input id="numero_end" value={dados.numero}
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
                {spedyEmpresaId && (
                  <label className="linha-checkbox" htmlFor="forcar_reprovisionamento">
                    <input
                      id="forcar_reprovisionamento" type="checkbox" checked={forcarReprovisionamento}
                      onChange={(e) => setForcarReprovisionamento(e.target.checked)}
                    />
                    <span>
                      Forçar reprovisionamento na Spedy — reaproveita o certificado já salvo e gera uma
                      chave nova. Use se a emissão começar a dar "Usuário não autenticado".
                    </span>
                  </label>
                )}
              </div>
            </div>
          )}
        </section>

        <details className="secao-config">
          <summary>
            <span className="resumo-secao">
              <h2>Certificado digital</h2>
              <span className="ajuda">
                {certificadoValidoAte
                  ? `Válido até ${new Date(certificadoValidoAte).toLocaleDateString("pt-BR")}`
                  : "Nenhum certificado válido cadastrado"}
              </span>
            </span>
            <span className="seta">▾</span>
          </summary>
          <p className="ajuda">Preencha os dois campos abaixo somente para trocar o certificado atual.</p>
          <div className="grade-campos">
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
          </div>
        </details>

        <div className="barra-salvar">
          <button type="submit" disabled={enviando}>{enviando ? "Salvando..." : "Salvar"}</button>
          {erro && <p className="erro">{erro}</p>}
          {sucesso && <p>{sucesso}</p>}
        </div>
      </form>
    </div>
  );
}
