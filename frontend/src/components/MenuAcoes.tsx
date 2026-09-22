import { useEffect, useRef, useState } from "react";

export type ItemMenuAcoes = { rotulo: string; onClick: () => void; perigo?: boolean };

/** Botao "Acoes" com um menu suspenso -- usado nas linhas da tabela de
 * emissoes que tem mais de 2 acoes possiveis, pra nao poluir a tela com uma
 * fileira inteira de botoes. Posiciona o painel com `position: fixed`
 * calculado a partir do botao (nao com CSS relative/absolute) porque a
 * tabela fica dentro de um `.rolagem-tabela` com overflow-x: auto, que
 * cortaria um menu posicionado normalmente perto da borda. */
export default function MenuAcoes({ itens }: { itens: ItemMenuAcoes[] }) {
  const [aberto, setAberto] = useState(false);
  const [posicao, setPosicao] = useState({ top: 0, right: 0 });
  const botaoRef = useRef<HTMLButtonElement>(null);
  const painelRef = useRef<HTMLDivElement>(null);

  function alternar() {
    if (aberto) {
      setAberto(false);
      return;
    }
    const retangulo = botaoRef.current?.getBoundingClientRect();
    if (retangulo) {
      setPosicao({ top: retangulo.bottom + 4, right: window.innerWidth - retangulo.right });
    }
    setAberto(true);
  }

  useEffect(() => {
    if (!aberto) return;

    function aoClicarFora(evento: MouseEvent) {
      const alvo = evento.target as Node;
      if (botaoRef.current?.contains(alvo) || painelRef.current?.contains(alvo)) return;
      setAberto(false);
    }
    function aoSoltarTecla(evento: KeyboardEvent) {
      if (evento.key === "Escape") setAberto(false);
    }
    function fechar() {
      setAberto(false);
    }

    document.addEventListener("mousedown", aoClicarFora);
    document.addEventListener("keydown", aoSoltarTecla);
    window.addEventListener("scroll", fechar, true);
    window.addEventListener("resize", fechar);
    return () => {
      document.removeEventListener("mousedown", aoClicarFora);
      document.removeEventListener("keydown", aoSoltarTecla);
      window.removeEventListener("scroll", fechar, true);
      window.removeEventListener("resize", fechar);
    };
  }, [aberto]);

  return (
    <>
      <button
        ref={botaoRef}
        type="button"
        className="secundario"
        aria-haspopup="true"
        aria-expanded={aberto}
        onClick={alternar}
      >
        Ações
      </button>
      {aberto && (
        <div
          ref={painelRef}
          className="menu-acoes-painel"
          style={{ top: posicao.top, right: posicao.right }}
          role="menu"
        >
          {itens.map((item) => (
            <button
              key={item.rotulo}
              type="button"
              role="menuitem"
              className={item.perigo ? "menu-acoes-item perigo" : "menu-acoes-item"}
              onClick={() => {
                setAberto(false);
                item.onClick();
              }}
            >
              {item.rotulo}
            </button>
          ))}
        </div>
      )}
    </>
  );
}
