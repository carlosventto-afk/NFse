import { useEffect, useRef, useState } from "react";

export type ItemComboBox = { id: string; rotulo: string; subRotulo?: string };

type Props = {
  itens: ItemComboBox[];
  valorId: string | null;
  aoSelecionar: (id: string | null) => void;
  marcador: string;
  rotuloNovo?: string;
  aoClicarNovo?: () => void;
  id?: string;
};

/** Campo de busca com lista suspensa -- digitar filtra por rotulo/subRotulo,
 * clicar num item seleciona. Mesma receita de posicionamento fixo do
 * MenuAcoes (calculado a partir do campo, nao relative/absolute) para
 * funcionar dentro de qualquer contêiner com overflow. Uma linha opcional
 * no fim da lista ("+ Cadastrar novo") delega a criação pro componente pai
 * em vez de tentar modelar o formulário de criação aqui dentro. */
export default function ComboBox({ itens, valorId, aoSelecionar, marcador, rotuloNovo, aoClicarNovo, id }: Props) {
  const selecionado = itens.find((item) => item.id === valorId) ?? null;
  const [aberto, setAberto] = useState(false);
  const [busca, setBusca] = useState("");
  const [posicao, setPosicao] = useState({ top: 0, left: 0, width: 0 });
  const campoRef = useRef<HTMLInputElement>(null);
  const painelRef = useRef<HTMLDivElement>(null);

  const termo = busca.trim().toLowerCase();
  const filtrados = termo
    ? itens.filter(
        (item) =>
          item.rotulo.toLowerCase().includes(termo) ||
          (item.subRotulo ?? "").toLowerCase().includes(termo),
      )
    : itens;

  function abrir() {
    const retangulo = campoRef.current?.getBoundingClientRect();
    if (retangulo) {
      setPosicao({ top: retangulo.bottom + 4, left: retangulo.left, width: retangulo.width });
    }
    setBusca("");
    setAberto(true);
  }

  function escolher(itemId: string | null) {
    aoSelecionar(itemId);
    setAberto(false);
    setBusca("");
  }

  useEffect(() => {
    if (!aberto) return;

    function aoClicarFora(evento: MouseEvent) {
      const alvo = evento.target as Node;
      if (campoRef.current?.contains(alvo) || painelRef.current?.contains(alvo)) return;
      setAberto(false);
      setBusca("");
    }
    function aoSoltarTecla(evento: KeyboardEvent) {
      if (evento.key === "Escape") {
        setAberto(false);
        setBusca("");
      }
    }
    function fechar() {
      setAberto(false);
      setBusca("");
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
    <div className="combo">
      <input
        id={id}
        ref={campoRef}
        className="combo-campo"
        placeholder={marcador}
        value={aberto ? busca : selecionado?.rotulo ?? ""}
        onFocus={abrir}
        onClick={abrir}
        onChange={(e) => setBusca(e.target.value)}
        autoComplete="off"
      />
      {aberto && (
        <div
          ref={painelRef}
          className="combo-painel"
          style={{ top: posicao.top, left: posicao.left, width: posicao.width }}
          role="listbox"
        >
          {selecionado && (
            <button type="button" className="combo-item combo-item-limpar" onClick={() => escolher(null)}>
              Limpar seleção
            </button>
          )}
          {filtrados.length === 0 && (
            <p className="combo-vazio">Nenhum resultado para "{busca}".</p>
          )}
          {filtrados.map((item) => (
            <button
              key={item.id}
              type="button"
              className="combo-item"
              role="option"
              aria-selected={item.id === valorId}
              onClick={() => escolher(item.id)}
            >
              <span>{item.rotulo}</span>
              {item.subRotulo && <span className="combo-item-sub">{item.subRotulo}</span>}
            </button>
          ))}
          {aoClicarNovo && rotuloNovo && (
            <button
              type="button"
              className="combo-item combo-item-novo"
              onClick={() => {
                setAberto(false);
                setBusca("");
                aoClicarNovo();
              }}
            >
              {rotuloNovo}
            </button>
          )}
        </div>
      )}
    </div>
  );
}
