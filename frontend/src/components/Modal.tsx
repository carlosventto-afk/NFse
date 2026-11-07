import { useEffect, type ReactNode } from "react";

type Props = { titulo: string; aoFechar: () => void; children: ReactNode };

export default function Modal({ titulo, aoFechar, children }: Props) {
  useEffect(() => {
    function aoSoltarTecla(evento: KeyboardEvent) {
      if (evento.key === "Escape") aoFechar();
    }
    document.addEventListener("keydown", aoSoltarTecla);
    return () => document.removeEventListener("keydown", aoSoltarTecla);
  }, [aoFechar]);

  return (
    <div className="modal-fundo" onMouseDown={(e) => { if (e.target === e.currentTarget) aoFechar(); }}>
      <div className="modal-caixa" role="dialog" aria-modal="true" aria-label={titulo}>
        <div className="modal-cabecalho">
          <h2>{titulo}</h2>
          <button type="button" className="modal-fechar" onClick={aoFechar} aria-label="Fechar">
            ×
          </button>
        </div>
        {children}
      </div>
    </div>
  );
}
