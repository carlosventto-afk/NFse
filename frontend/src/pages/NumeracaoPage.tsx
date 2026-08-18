import { useEffect, useState, type FormEvent } from "react";
import { definirNumeracao, obterNumeracao } from "../api/empresas";

export default function NumeracaoPage() {
  const [serie, setSerie] = useState("");
  const [proximoNumero, setProximoNumero] = useState("");
  const [carregando, setCarregando] = useState(true);
  const [salvando, setSalvando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [sucesso, setSucesso] = useState<string | null>(null);

  useEffect(() => {
    obterNumeracao()
      .then((dados) => {
        setSerie(dados.serie);
        setProximoNumero(String(dados.proximo_numero));
      })
      .catch((e) => setErro(e instanceof Error ? e.message : "Nao foi possivel carregar a numeracao"))
      .finally(() => setCarregando(false));
  }, []);

  async function salvar(evento: FormEvent) {
    evento.preventDefault();
    setErro(null);
    setSucesso(null);
    setSalvando(true);
    try {
      const dados = await definirNumeracao({ serie, proximo_numero: Number(proximoNumero) });
      setSerie(dados.serie);
      setProximoNumero(String(dados.proximo_numero));
      setSucesso("Numeracao atualizada.");
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel salvar a numeracao");
    } finally {
      setSalvando(false);
    }
  }

  if (carregando) {
    return <p>Carregando...</p>;
  }

  return (
    <div className="cartao">
      <h1>Numeracao das notas</h1>
      <p>
        Define a serie e o proximo numero de DPS a ser usado na proxima emissao
        desta empresa. Util para continuar a numeracao de um sistema anterior.
      </p>
      <form onSubmit={salvar}>
        <div className="form-linha">
          <label htmlFor="serie">Serie</label>
          <input id="serie" required maxLength={5} value={serie} onChange={(e) => setSerie(e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="proximo_numero">Proximo numero</label>
          <input
            id="proximo_numero" type="number" min={1} required
            value={proximoNumero} onChange={(e) => setProximoNumero(e.target.value)}
          />
        </div>
        {erro && <p className="erro">{erro}</p>}
        {sucesso && <p>{sucesso}</p>}
        <button type="submit" disabled={salvando}>{salvando ? "Salvando..." : "Salvar"}</button>
      </form>
    </div>
  );
}
