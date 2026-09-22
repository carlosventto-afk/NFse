/** Simbolo da VTR (hexagono-escudo + check), conforme o plano de marca:
 * hexagono regular 168x168, raio 80 centrado em (84,84); check com traco de
 * 14 unidades, ponta e juncao arredondadas; ponto de destaque de 8 unidades
 * na ponta superior direita do check.
 *
 * variante="cor": hexagono preenchido em Azul Profundo -- so para fundos
 * claros (regra da marca: nunca aplicar a versao cheia sobre fundo escuro).
 * variante="contorno": hexagono como TRACO (sem preenchimento) em
 * Verde-agua claro -- usado no menu lateral, que ja e Azul Profundo; um
 * hexagono preenchido nessa cor desapareceria contra o proprio fundo, e o
 * contorno evita isso sem recorrer a uma versao monocromatica solida que
 * perderia a forma do escudo. */
const PONTOS_HEXAGONO = "164,84 124,14.7 44,14.7 4,84 44,153.3 124,153.3";
const TRACADO_CHECK = "M50 88 L76 114 L122 56";

export default function LogoVTR({
  variante = "cor",
  tamanho = 32,
}: {
  variante?: "cor" | "contorno";
  tamanho?: number;
}) {
  const corContorno = "#57C2A8";
  return (
    <svg width={tamanho} height={tamanho} viewBox="0 0 168 168" aria-hidden="true">
      {variante === "cor" ? (
        <polygon points={PONTOS_HEXAGONO} fill="#14213D" />
      ) : (
        <polygon points={PONTOS_HEXAGONO} fill="none" stroke={corContorno} strokeWidth="6" strokeLinejoin="round" />
      )}
      <path
        d={TRACADO_CHECK}
        fill="none"
        stroke="#F6F2EA"
        strokeWidth="14"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      <circle cx="122" cy="56" r="8" fill={variante === "cor" ? "#2FA98C" : corContorno} />
    </svg>
  );
}
