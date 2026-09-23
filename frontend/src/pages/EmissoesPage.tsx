import { useEffect, useState } from "react";
import {
  cancelarEmissao, emitirEmissao, emitirEmissoesLote, excluirEmissao, excluirEmissoesLote, listarEmissoes,
  urlDownloadPdfsLote, urlDownloadXmlsLote, urlPdf, urlRequisicaoBruta, urlRespostaBruta, urlXml,
} from "../api/emissoes";
import type { TipoFiltroData } from "../api/emissoes";
import { obterToken } from "../api/client";
import type { Emissao } from "../api/types";
import MenuAcoes from "../components/MenuAcoes";
import { CLASSES_PILULA, ROTULOS_STATUS } from "../lib/status";

const STATUS = [
  "", "aguardando_emissao", "pendente", "autorizada", "rejeitada", "cancelada",
  "cancelamento_pendente", "erro_cancelamento",
];

function PilulaStatus({ status }: { status: string }) {
  const classe = CLASSES_PILULA[status] ?? "cancelada";
  return <span className={`pilula ${classe}`}>{ROTULOS_STATUS[status] ?? status}</span>;
}

function salvarBlobComoArquivo(blob: Blob, nomeArquivo: string) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = nomeArquivo;
  link.click();
  URL.revokeObjectURL(link.href);
}

async function extrairDetalheErro(resposta: Response, generico: string): Promise<string> {
  try {
    const corpo = await resposta.json();
    return corpo.detail ?? generico;
  } catch {
    return generico;
  }
}

export default function EmissoesPage() {
  const [emissoes, setEmissoes] = useState<Emissao[]>([]);
  const [filtroStatus, setFiltroStatus] = useState("");
  const [filtroTipoData, setFiltroTipoData] = useState<TipoFiltroData>("competencia");
  const [filtroInicio, setFiltroInicio] = useState("");
  const [filtroFim, setFiltroFim] = useState("");
  const [selecionados, setSelecionados] = useState<Set<string>>(new Set());
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [cancelandoId, setCancelandoId] = useState<string | null>(null);
  const [motivo, setMotivo] = useState("");
  const [codigoMotivo, setCodigoMotivo] = useState("9");

  async function carregar() {
    setCarregando(true);
    setErro(null);
    setSelecionados(new Set());
    try {
      setEmissoes(
        await listarEmissoes(filtroStatus || undefined, filtroTipoData, filtroInicio || undefined, filtroFim || undefined),
      );
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel carregar as emissoes");
    } finally {
      setCarregando(false);
    }
  }

  useEffect(() => {
    carregar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtroStatus, filtroTipoData, filtroInicio, filtroFim]);

  const todosSelecionados = emissoes.length > 0 && emissoes.every((e) => selecionados.has(e.id));

  function alternarSelecao(id: string) {
    setSelecionados((atual) => {
      const novo = new Set(atual);
      if (novo.has(id)) {
        novo.delete(id);
      } else {
        novo.add(id);
      }
      return novo;
    });
  }

  function alternarSelecaoTodos() {
    setSelecionados(todosSelecionados ? new Set() : new Set(emissoes.map((e) => e.id)));
  }

  async function confirmarCancelamento(id: string) {
    setErro(null);
    try {
      await cancelarEmissao(id, motivo, codigoMotivo);
      setCancelandoId(null);
      setMotivo("");
      await carregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel cancelar a emissao");
    }
  }

  async function excluir(id: string) {
    if (!window.confirm("Excluir esta emissao? Essa acao nao pode ser desfeita.")) {
      return;
    }
    setErro(null);
    try {
      await excluirEmissao(id);
      await carregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel excluir a emissao");
    }
  }

  async function emitir(id: string) {
    setErro(null);
    try {
      await emitirEmissao(id);
      await carregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel emitir a emissao");
    }
  }

  async function emitirSelecionados() {
    setErro(null);
    try {
      const resultado = await emitirEmissoesLote(Array.from(selecionados));
      if (resultado.puladas > 0) {
        setErro(
          `${resultado.emitidas} enviada(s) pra emissao; ${resultado.puladas} nao pode(m) ser `
          + "emitida(s) (status nao esta aguardando emissao)",
        );
      }
      await carregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel emitir as emissoes selecionadas");
    }
  }

  async function excluirSelecionados() {
    if (!window.confirm(`Excluir ${selecionados.size} emissoes selecionadas? Essa acao nao pode ser desfeita.`)) {
      return;
    }
    setErro(null);
    try {
      const resultado = await excluirEmissoesLote(Array.from(selecionados));
      if (resultado.puladas > 0) {
        setErro(
          `${resultado.excluidas} excluida(s); ${resultado.puladas} nao pode(m) ser excluida(s) `
          + "(nota autorizada em producao ou status nao elegivel)",
        );
      }
      await carregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel excluir as emissoes selecionadas");
    }
  }

  async function baixar(url: string, nomeArquivo: string) {
    const token = obterToken();
    const resposta = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!resposta.ok) {
      setErro(await extrairDetalheErro(resposta, "Nao foi possivel baixar o arquivo"));
      return;
    }
    salvarBlobComoArquivo(await resposta.blob(), nomeArquivo);
  }

  async function baixarSelecionados(url: string, nomeArquivo: string) {
    const token = obterToken();
    const resposta = await fetch(url, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ ids: Array.from(selecionados) }),
    });
    if (!resposta.ok) {
      setErro(await extrairDetalheErro(resposta, "Nao foi possivel baixar os arquivos selecionados"));
      return;
    }
    salvarBlobComoArquivo(await resposta.blob(), nomeArquivo);
  }

  const totalNotas = emissoes.length;
  const valorTotal = emissoes.reduce((soma, e) => soma + Number(e.valor), 0);

  return (
    <div>
      <h1>Emissões</h1>
      <div className="totalizador">
        <span><strong>{totalNotas}</strong> nota{totalNotas === 1 ? "" : "s"}</span>
        <span>Total: <strong>R$ {valorTotal.toFixed(2)}</strong></span>
      </div>
      <div className="painel-filtros">
        <div className="form-linha">
          <label htmlFor="status">Filtrar por status</label>
          <select id="status" value={filtroStatus} onChange={(e) => setFiltroStatus(e.target.value)}>
            {STATUS.map((s) => <option key={s} value={s}>{s ? ROTULOS_STATUS[s] ?? s : "Todos"}</option>)}
          </select>
        </div>
        <div className="form-linha">
          <label htmlFor="tipo_data">Filtrar por</label>
          <select
            id="tipo_data" value={filtroTipoData}
            onChange={(e) => setFiltroTipoData(e.target.value as TipoFiltroData)}
          >
            <option value="competencia">Competência</option>
            <option value="data_venda">Data Venda</option>
          </select>
        </div>
        <div className="form-linha">
          <label htmlFor="data_inicio">De</label>
          <input id="data_inicio" type="date" value={filtroInicio} onChange={(e) => setFiltroInicio(e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="data_fim">Até</label>
          <input id="data_fim" type="date" value={filtroFim} onChange={(e) => setFiltroFim(e.target.value)} />
        </div>
      </div>

      {selecionados.size > 0 && (
        <div className="barra-selecao">
          <span className="contagem">{selecionados.size} selecionada{selecionados.size > 1 ? "s" : ""}</span>
          <button className="secundario" onClick={() => baixarSelecionados(urlDownloadXmlsLote(), "notas_xml.zip")}>
            Baixar XMLs selecionados
          </button>
          <button className="secundario" onClick={() => baixarSelecionados(urlDownloadPdfsLote(), "notas_pdf.zip")}>
            Baixar PDFs selecionados
          </button>
          {selecionados.size > 1 && (
            <>
              <button onClick={emitirSelecionados}>Emitir/reemitir selecionadas</button>
              <button className="perigo" onClick={excluirSelecionados}>
                Excluir selecionadas
              </button>
            </>
          )}
        </div>
      )}

      {erro && <p className="erro">{erro}</p>}

      {carregando ? (
        <p>Carregando...</p>
      ) : (
        <div className="painel-tabela">
          <div className="rolagem-tabela">
            <table>
              <thead>
                <tr>
                  <th className="col-check"><input type="checkbox" checked={todosSelecionados} onChange={alternarSelecaoTodos} /></th>
                  <th>Número</th><th>Origem</th><th>Status</th><th className="col-valor">Valor</th><th>Competência</th><th>Data Venda</th><th>Produto</th><th>Tipo</th><th>Bandeira</th><th>Erro</th><th></th>
                </tr>
              </thead>
              <tbody>
                {emissoes.map((emissao) => (
                  <tr key={emissao.id}>
                    <td className="col-check">
                      <input
                        type="checkbox"
                        checked={selecionados.has(emissao.id)}
                        onChange={() => alternarSelecao(emissao.id)}
                      />
                    </td>
                    <td className="num">{emissao.serie}/{emissao.numero}</td>
                    <td>{emissao.origem}</td>
                    <td><PilulaStatus status={emissao.status} /></td>
                    <td className="col-valor num">R$ {emissao.valor}</td>
                    <td>{emissao.competencia}</td>
                    <td>{emissao.data_vencimento ?? "—"}</td>
                    <td>{emissao.produto ?? "—"}</td>
                    <td>{emissao.tipo_produto ?? "—"}</td>
                    <td>{emissao.bandeira ?? "—"}</td>
                    <td>
                      {emissao.erros ? (
                        <span className="erro-texto" title={emissao.erros}>{emissao.erros}</span>
                      ) : (
                        <span className="sem-erro">—</span>
                      )}
                    </td>
                    <td className="celula-acoes">
                      {emissao.status === "aguardando_emissao" && (
                        <>
                          <button onClick={() => emitir(emissao.id)}>Emitir</button>
                          <button className="perigo" onClick={() => excluir(emissao.id)}>Excluir</button>
                        </>
                      )}
                      {emissao.status === "pendente" && (
                        <button className="perigo" onClick={() => excluir(emissao.id)}>Excluir</button>
                      )}
                      {emissao.status === "autorizada" && (
                        <>
                          <button className="secundario" onClick={() => baixar(urlPdf(emissao.id), `NFSe_${emissao.serie}_${emissao.numero}.pdf`)}>PDF</button>
                          <MenuAcoes
                            itens={[
                              { rotulo: "XML", onClick: () => baixar(urlXml(emissao.id), `NFSe_${emissao.serie}_${emissao.numero}.xml`) },
                              { rotulo: "Cancelar", perigo: true, onClick: () => setCancelandoId(emissao.id) },
                              { rotulo: "Excluir", perigo: true, onClick: () => excluir(emissao.id) },
                            ]}
                          />
                        </>
                      )}
                      {emissao.status === "rejeitada" && (
                        <>
                          <button onClick={() => emitir(emissao.id)}>Reemitir</button>
                          <MenuAcoes
                            itens={[
                              { rotulo: "XML", onClick: () => baixar(urlXml(emissao.id), `DPS_${emissao.serie}_${emissao.numero}.xml`) },
                              { rotulo: "Resposta SEFIN", onClick: () => baixar(urlRespostaBruta(emissao.id), `RESPOSTA_${emissao.serie}_${emissao.numero}.json`) },
                              { rotulo: "Requisição enviada", onClick: () => baixar(urlRequisicaoBruta(emissao.id), `REQUISICAO_${emissao.serie}_${emissao.numero}.json`) },
                              { rotulo: "Excluir", perigo: true, onClick: () => excluir(emissao.id) },
                            ]}
                          />
                        </>
                      )}
                      {(
                        emissao.status === "cancelamento_aguardando_confirmacao"
                        || emissao.status === "erro_cancelamento"
                      ) && (
                        <button
                          className="secundario"
                          onClick={() => baixar(urlRespostaBruta(emissao.id), `RESPOSTA_${emissao.serie}_${emissao.numero}.json`)}
                        >
                          Resposta SEFIN
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}

      {cancelandoId && (
        <div className="cartao">
          <h2>Cancelar emissao</h2>
          <div className="form-linha">
            <label htmlFor="codigo_motivo">Motivo</label>
            <select id="codigo_motivo" value={codigoMotivo} onChange={(e) => setCodigoMotivo(e.target.value)}>
              <option value="1">Erro na emissao</option>
              <option value="2">Servico nao prestado</option>
              <option value="9">Outros</option>
            </select>
          </div>
          <div className="form-linha">
            <label htmlFor="motivo">Detalhe</label>
            <input id="motivo" required value={motivo} onChange={(e) => setMotivo(e.target.value)} />
          </div>
          <button onClick={() => confirmarCancelamento(cancelandoId)}>Confirmar cancelamento</button>
          <button className="secundario" onClick={() => setCancelandoId(null)}>Voltar</button>
        </div>
      )}
    </div>
  );
}
