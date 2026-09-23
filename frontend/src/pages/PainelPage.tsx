import { useEffect, useState } from "react";
import {
  Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { buscarResumoDashboard } from "../api/dashboard";
import type { DashboardResumo, GrupoResumo } from "../api/types";
import { corPorChave, CORES_BANDEIRA, CORES_TIPO_PRODUTO } from "../lib/cores";
import { CORES_STATUS, ROTULOS_STATUS } from "../lib/status";

function mesAtualISO(): string {
  const agora = new Date();
  return `${agora.getFullYear()}-${String(agora.getMonth() + 1).padStart(2, "0")}`;
}

function formatarDataCurta(iso: string): string {
  const [, mes, dia] = iso.split("-");
  return `${dia}/${mes}`;
}

function formatarValor(valor: string): string {
  return `R$ ${valor}`;
}

interface BlocoResumoProps {
  titulo: string;
  grupos: GrupoResumo[];
  corPara: (chave: string | null) => string;
  rotuloPara: (chave: string | null) => string;
}

function BlocoResumo({ titulo, grupos, corPara, rotuloPara }: BlocoResumoProps) {
  const ordenados = [...grupos].sort((a, b) => Number(b.valor) - Number(a.valor));
  const maiorValor = Math.max(1, ...ordenados.map((g) => Number(g.valor)));

  return (
    <div className="bloco-resumo">
      <h2>{titulo}</h2>
      {ordenados.length === 0 ? (
        <p className="ajuda">Sem dados nessa competência.</p>
      ) : (
        <ul className="lista-resumo">
          {ordenados.map((grupo) => (
            <li key={grupo.chave ?? "—"} className="linha-resumo">
              <div className="linha-resumo-rotulo">
                <span className="ponto-cor" style={{ background: corPara(grupo.chave) }} />
                <span>{rotuloPara(grupo.chave)}</span>
                <span className="linha-resumo-qtd">{grupo.quantidade}</span>
              </div>
              <div className="barra-resumo-trilho">
                <div
                  className="barra-resumo-preenchimento"
                  style={{
                    width: `${(Number(grupo.valor) / maiorValor) * 100}%`,
                    background: corPara(grupo.chave),
                  }}
                />
              </div>
              <span className="linha-resumo-valor">{formatarValor(grupo.valor)}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

function TooltipDiario({ active, payload }: { active?: boolean; payload?: Array<{ payload: DashboardResumo["serie_diaria"][number] }> }) {
  if (!active || !payload || payload.length === 0) return null;
  const ponto = payload[0].payload;
  return (
    <div className="tooltip-grafico">
      <strong>{formatarDataCurta(ponto.data)}</strong>
      <div>{formatarValor(ponto.valor)}</div>
      <div className="ajuda">{ponto.quantidade} nota{ponto.quantidade === 1 ? "" : "s"}</div>
    </div>
  );
}

export default function PainelPage() {
  const [mes, setMes] = useState(mesAtualISO());
  const [resumo, setResumo] = useState<DashboardResumo | null>(null);
  const [carregando, setCarregando] = useState(true);
  const [erro, setErro] = useState<string | null>(null);

  useEffect(() => {
    let cancelado = false;
    setCarregando(true);
    setErro(null);
    buscarResumoDashboard(`${mes}-01`)
      .then((dados) => { if (!cancelado) setResumo(dados); })
      .catch((e) => { if (!cancelado) setErro(e instanceof Error ? e.message : "Não foi possível carregar o painel"); })
      .finally(() => { if (!cancelado) setCarregando(false); });
    return () => { cancelado = true; };
  }, [mes]);

  return (
    <div>
      <h1>Painel</h1>
      <div className="painel-filtros">
        <div className="form-linha">
          <label htmlFor="mes_competencia">Competência</label>
          <input id="mes_competencia" type="month" value={mes} onChange={(e) => setMes(e.target.value)} />
        </div>
      </div>

      {erro && <p className="erro">{erro}</p>}
      {carregando && <p>Carregando...</p>}

      {!carregando && resumo && (
        <>
          <div className="painel-metricas">
            <div className="cartao-metrica">
              <span className="rotulo-metrica">Total de notas</span>
              <span className="valor-metrica">{resumo.total_notas}</span>
            </div>
            <div className="cartao-metrica">
              <span className="rotulo-metrica">Valor total</span>
              <span className="valor-metrica">{formatarValor(resumo.valor_total)}</span>
            </div>
          </div>

          <div className="painel-blocos">
            <BlocoResumo
              titulo="Por status" grupos={resumo.por_status}
              corPara={(chave) => corPorChave(CORES_STATUS, chave)}
              rotuloPara={(chave) => (chave ? ROTULOS_STATUS[chave] ?? chave : "—")}
            />
            <BlocoResumo
              titulo="Por tipo de produto" grupos={resumo.por_tipo_produto}
              corPara={(chave) => corPorChave(CORES_TIPO_PRODUTO, chave)}
              rotuloPara={(chave) => chave ?? "—"}
            />
            <BlocoResumo
              titulo="Por bandeira" grupos={resumo.por_bandeira}
              corPara={(chave) => corPorChave(CORES_BANDEIRA, chave)}
              rotuloPara={(chave) => chave ?? "Sem bandeira"}
            />
          </div>

          <div className="painel-grafico">
            <h2>Valores por dia de venda</h2>
            {resumo.serie_diaria.length === 0 ? (
              <p className="ajuda">Sem vendas com data registrada nessa competência.</p>
            ) : (
              <ResponsiveContainer width="100%" height={280}>
                <BarChart
                  data={resumo.serie_diaria.map((p) => ({ ...p, valorNumerico: Number(p.valor) }))}
                  margin={{ top: 8, right: 8, left: 8, bottom: 8 }}
                >
                  <CartesianGrid vertical={false} stroke="var(--borda)" />
                  <XAxis
                    dataKey="data" tickFormatter={formatarDataCurta}
                    stroke="var(--texto-suave)" fontSize={12} tickLine={false} axisLine={false}
                  />
                  <YAxis stroke="var(--texto-suave)" fontSize={12} tickLine={false} axisLine={false} width={40} />
                  <Tooltip content={<TooltipDiario />} cursor={{ fill: "var(--superficie-alt)" }} />
                  <Bar dataKey="valorNumerico" fill="var(--acento)" radius={[4, 4, 0, 0]} maxBarSize={36} />
                </BarChart>
              </ResponsiveContainer>
            )}
          </div>
        </>
      )}
    </div>
  );
}
