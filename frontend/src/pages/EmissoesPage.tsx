import { useEffect, useState } from "react";
import {
  cancelarEmissao, excluirEmissao, listarEmissoes,
  urlDownloadPdfsLote, urlDownloadXmlsLote, urlPdf, urlRespostaBruta, urlXml,
} from "../api/emissoes";
import { obterToken } from "../api/client";
import type { Emissao } from "../api/types";

const STATUS = ["", "pendente", "autorizada", "rejeitada", "cancelada", "cancelamento_pendente", "erro_cancelamento"];

function salvarBlobComoArquivo(blob: Blob, nomeArquivo: string) {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(blob);
  link.download = nomeArquivo;
  link.click();
  URL.revokeObjectURL(link.href);
}

export default function EmissoesPage() {
  const [emissoes, setEmissoes] = useState<Emissao[]>([]);
  const [filtroStatus, setFiltroStatus] = useState("");
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
      setEmissoes(await listarEmissoes(filtroStatus || undefined, filtroInicio || undefined, filtroFim || undefined));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel carregar as emissoes");
    } finally {
      setCarregando(false);
    }
  }

  useEffect(() => {
    carregar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtroStatus, filtroInicio, filtroFim]);

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

  async function baixar(url: string, nomeArquivo: string) {
    const token = obterToken();
    const resposta = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!resposta.ok) {
      setErro("Nao foi possivel baixar o arquivo");
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
      setErro("Nao foi possivel baixar os arquivos selecionados");
      return;
    }
    salvarBlobComoArquivo(await resposta.blob(), nomeArquivo);
  }

  return (
    <div>
      <h1>Emissoes</h1>
      <div style={{ display: "flex", gap: "1.5rem", flexWrap: "wrap" }}>
        <div className="form-linha" style={{ maxWidth: 240 }}>
          <label htmlFor="status">Filtrar por status</label>
          <select id="status" value={filtroStatus} onChange={(e) => setFiltroStatus(e.target.value)}>
            {STATUS.map((s) => <option key={s} value={s}>{s || "Todos"}</option>)}
          </select>
        </div>
        <div className="form-linha">
          <label htmlFor="data_inicio">De</label>
          <input id="data_inicio" type="date" value={filtroInicio} onChange={(e) => setFiltroInicio(e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="data_fim">Ate</label>
          <input id="data_fim" type="date" value={filtroFim} onChange={(e) => setFiltroFim(e.target.value)} />
        </div>
      </div>

      {selecionados.size > 0 && (
        <div className="form-linha" style={{ flexDirection: "row", gap: "0.5rem" }}>
          <button className="secundario" onClick={() => baixarSelecionados(urlDownloadXmlsLote(), "notas_xml.zip")}>
            Baixar XMLs selecionados ({selecionados.size})
          </button>
          <button className="secundario" onClick={() => baixarSelecionados(urlDownloadPdfsLote(), "notas_pdf.zip")}>
            Baixar PDFs selecionados ({selecionados.size})
          </button>
        </div>
      )}

      {erro && <p className="erro">{erro}</p>}

      {carregando ? (
        <p>Carregando...</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th><input type="checkbox" checked={todosSelecionados} onChange={alternarSelecaoTodos} /></th>
              <th>Numero</th><th>Origem</th><th>Status</th><th>Valor</th><th>Competencia</th><th>Erro</th><th></th>
            </tr>
          </thead>
          <tbody>
            {emissoes.map((emissao) => (
              <tr key={emissao.id}>
                <td>
                  <input
                    type="checkbox"
                    checked={selecionados.has(emissao.id)}
                    onChange={() => alternarSelecao(emissao.id)}
                  />
                </td>
                <td>{emissao.serie}/{emissao.numero}</td>
                <td>{emissao.origem}</td>
                <td>{emissao.status}</td>
                <td>R$ {emissao.valor}</td>
                <td>{emissao.competencia}</td>
                <td className="erro" style={{ maxWidth: 320, wordBreak: "break-word" }}>
                  {emissao.erros ?? ""}
                </td>
                <td>
                  {emissao.status === "autorizada" && (
                    <>
                      <button className="secundario" onClick={() => baixar(urlXml(emissao.id), `${emissao.chave_acesso}.xml`)}>XML</button>
                      <button className="secundario" onClick={() => baixar(urlPdf(emissao.id), `${emissao.chave_acesso}.pdf`)}>PDF</button>
                      <button className="perigo" onClick={() => setCancelandoId(emissao.id)}>Cancelar</button>
                    </>
                  )}
                  {emissao.status === "rejeitada" && (
                    <>
                      <button
                        className="secundario"
                        onClick={() => baixar(urlXml(emissao.id), `DPS_${emissao.serie}_${emissao.numero}.xml`)}
                      >
                        XML
                      </button>
                      <button
                        className="secundario"
                        onClick={() => baixar(urlRespostaBruta(emissao.id), `RESPOSTA_${emissao.serie}_${emissao.numero}.json`)}
                      >
                        Resposta SEFIN
                      </button>
                    </>
                  )}
                  {(emissao.status === "pendente" || emissao.status === "rejeitada") && (
                    <button className="perigo" onClick={() => excluir(emissao.id)}>Excluir</button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
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
