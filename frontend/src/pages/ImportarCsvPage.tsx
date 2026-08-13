import { useState } from "react";
import { confirmarCsv, previewCsv } from "../api/emissoes";
import type { ResultadoImportacaoCsv } from "../api/types";

export default function ImportarCsvPage() {
  const [arquivo, setArquivo] = useState<File | null>(null);
  const [preview, setPreview] = useState<ResultadoImportacaoCsv | null>(null);
  const [resultado, setResultado] = useState<ResultadoImportacaoCsv | null>(null);
  const [erro, setErro] = useState<string | null>(null);
  const [processando, setProcessando] = useState(false);

  async function verPreview() {
    if (!arquivo) return;
    setErro(null);
    setResultado(null);
    setProcessando(true);
    try {
      setPreview(await previewCsv(arquivo));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel ler o arquivo");
    } finally {
      setProcessando(false);
    }
  }

  async function confirmar() {
    if (!arquivo) return;
    setErro(null);
    setProcessando(true);
    try {
      setResultado(await confirmarCsv(arquivo));
      setPreview(null);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel confirmar a importacao");
    } finally {
      setProcessando(false);
    }
  }

  return (
    <div className="cartao">
      <h1>Importar CSV da Stone</h1>
      <div className="form-linha">
        <input type="file" accept=".csv" onChange={(e) => {
          setArquivo(e.target.files?.[0] ?? null);
          setPreview(null);
          setResultado(null);
        }} />
      </div>
      <button onClick={verPreview} disabled={!arquivo || processando}>Ver previa</button>

      {erro && <p className="erro">{erro}</p>}

      {preview && (
        <div>
          <h2>Previa</h2>
          <p>{preview.total_notas} notas, total R$ {preview.valor_total}</p>
          <p>
            Ignoradas — status nao pago: {preview.ignoradas.status_nao_pago},
            categoria nao venda: {preview.ignoradas.categoria_nao_venda},
            linha invalida: {preview.ignoradas.linha_invalida},
            ja emitida: {preview.ignoradas.ja_emitida_anteriormente}
          </p>
          <button onClick={confirmar} disabled={processando}>Confirmar importacao</button>
        </div>
      )}

      {resultado && (
        <div>
          <h2>Importacao confirmada</h2>
          <p>{resultado.total_notas} notas criadas, total R$ {resultado.valor_total}</p>
        </div>
      )}
    </div>
  );
}
