import { useEffect, useState } from "react";
import { cancelarEmissao, listarEmissoes, urlPdf, urlXml } from "../api/emissoes";
import { obterToken } from "../api/client";
import type { Emissao } from "../api/types";

const STATUS = ["", "pendente", "autorizada", "rejeitada", "cancelada", "cancelamento_pendente", "erro_cancelamento"];

export default function EmissoesPage() {
  const [emissoes, setEmissoes] = useState<Emissao[]>([]);
  const [filtroStatus, setFiltroStatus] = useState("");
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);
  const [cancelandoId, setCancelandoId] = useState<string | null>(null);
  const [motivo, setMotivo] = useState("");
  const [codigoMotivo, setCodigoMotivo] = useState("9");

  async function carregar() {
    setCarregando(true);
    setErro(null);
    try {
      setEmissoes(await listarEmissoes(filtroStatus || undefined));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel carregar as emissoes");
    } finally {
      setCarregando(false);
    }
  }

  useEffect(() => {
    carregar();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filtroStatus]);

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

  async function baixar(url: string, nomeArquivo: string) {
    const token = obterToken();
    const resposta = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
    if (!resposta.ok) {
      setErro("Nao foi possivel baixar o arquivo");
      return;
    }
    const blob = await resposta.blob();
    const link = document.createElement("a");
    link.href = URL.createObjectURL(blob);
    link.download = nomeArquivo;
    link.click();
    URL.revokeObjectURL(link.href);
  }

  return (
    <div>
      <h1>Emissoes</h1>
      <div className="form-linha" style={{ maxWidth: 240 }}>
        <label htmlFor="status">Filtrar por status</label>
        <select id="status" value={filtroStatus} onChange={(e) => setFiltroStatus(e.target.value)}>
          {STATUS.map((s) => <option key={s} value={s}>{s || "Todos"}</option>)}
        </select>
      </div>

      {erro && <p className="erro">{erro}</p>}

      {carregando ? (
        <p>Carregando...</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Numero</th><th>Origem</th><th>Status</th><th>Valor</th><th>Competencia</th><th></th>
            </tr>
          </thead>
          <tbody>
            {emissoes.map((emissao) => (
              <tr key={emissao.id}>
                <td>{emissao.serie}/{emissao.numero}</td>
                <td>{emissao.origem}</td>
                <td>{emissao.status}</td>
                <td>R$ {emissao.valor}</td>
                <td>{emissao.competencia}</td>
                <td>
                  {emissao.status === "autorizada" && (
                    <>
                      <button className="secundario" onClick={() => baixar(urlXml(emissao.id), `${emissao.chave_acesso}.xml`)}>XML</button>
                      <button className="secundario" onClick={() => baixar(urlPdf(emissao.id), `${emissao.chave_acesso}.pdf`)}>PDF</button>
                      <button className="perigo" onClick={() => setCancelandoId(emissao.id)}>Cancelar</button>
                    </>
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
