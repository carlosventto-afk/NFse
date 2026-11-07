import { useState } from "react";
import {
  atualizarModeloDescricao, criarModeloDescricao, removerModeloDescricao,
} from "../api/modelosDescricao";
import type { Cliente, ModeloDescricao } from "../api/types";
import ComboBox from "./ComboBox";
import Modal from "./Modal";

const VAZIO = { titulo: "", texto: "", cliente_id: null as string | null };

type Props = {
  modelos: ModeloDescricao[];
  clientes: Cliente[];
  aoFechar: () => void;
  aoAtualizarModelos: (modelos: ModeloDescricao[]) => void;
};

/** Tela de gerenciamento dos modelos de descrição -- separada do fluxo
 * principal de emissão porque é uma tarefa de configuração ocasional
 * ("mexer na prateleira"), não algo que se faz nota a nota. */
export default function GerenciarModelosModal({ modelos, clientes, aoFechar, aoAtualizarModelos }: Props) {
  const [editandoId, setEditandoId] = useState<string | null>(null);
  const [form, setForm] = useState(VAZIO);
  const [erro, setErro] = useState<string | null>(null);
  const [salvando, setSalvando] = useState(false);

  function nomeDoCliente(clienteId: string | null): string | null {
    if (!clienteId) return null;
    return clientes.find((c) => c.id === clienteId)?.nome ?? null;
  }

  function iniciarEdicao(modelo: ModeloDescricao) {
    setEditandoId(modelo.id);
    setForm({ titulo: modelo.titulo, texto: modelo.texto, cliente_id: modelo.cliente_id });
    setErro(null);
  }

  function cancelarEdicao() {
    setEditandoId(null);
    setForm(VAZIO);
    setErro(null);
  }

  async function salvar() {
    if (!form.titulo.trim() || !form.texto.trim()) {
      setErro("Preencha o título e o texto do modelo.");
      return;
    }
    setErro(null);
    setSalvando(true);
    try {
      if (editandoId) {
        const atualizado = await atualizarModeloDescricao(editandoId, form);
        aoAtualizarModelos(modelos.map((m) => (m.id === editandoId ? atualizado : m)));
      } else {
        const criado = await criarModeloDescricao(form);
        aoAtualizarModelos([...modelos, criado]);
      }
      cancelarEdicao();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível salvar o modelo");
    } finally {
      setSalvando(false);
    }
  }

  async function remover(id: string) {
    try {
      await removerModeloDescricao(id);
      aoAtualizarModelos(modelos.filter((m) => m.id !== id));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível remover o modelo");
    }
  }

  return (
    <Modal titulo="Modelos de descrição" aoFechar={aoFechar}>
      <p className="ajuda">
        Textos prontos para a descrição do serviço. Vincule um modelo a um cliente para que ele
        preencha a descrição automaticamente quando esse cliente for selecionado na emissão.
      </p>

      {modelos.length > 0 && (
        <ul className="lista-modelos">
          {modelos.map((modelo) => (
            <li key={modelo.id} className="item-modelo">
              <div className="item-modelo-texto">
                <strong>
                  {modelo.titulo}
                  {nomeDoCliente(modelo.cliente_id) && ` — ${nomeDoCliente(modelo.cliente_id)}`}
                </strong>
                <span>{modelo.texto}</span>
              </div>
              <div className="item-modelo-acoes">
                <button type="button" className="secundario" onClick={() => iniciarEdicao(modelo)}>
                  Editar
                </button>
                <button type="button" className="perigo" onClick={() => remover(modelo.id)}>
                  Remover
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <div className="expansor">
        <h2>{editandoId ? "Editar modelo" : "Novo modelo"}</h2>
        <div className="form-linha">
          <label htmlFor="modelo-titulo">Título</label>
          <input
            id="modelo-titulo" value={form.titulo}
            onChange={(e) => setForm((f) => ({ ...f, titulo: e.target.value }))}
            placeholder="Ex.: Consultoria mensal"
          />
        </div>
        <div className="form-linha">
          <label htmlFor="modelo-cliente">Vincular a um cliente (opcional)</label>
          <ComboBox
            id="modelo-cliente"
            itens={clientes.map((c) => ({ id: c.id, rotulo: c.nome, subRotulo: c.cpf_cnpj ?? undefined }))}
            valorId={form.cliente_id}
            aoSelecionar={(id) => setForm((f) => ({ ...f, cliente_id: id }))}
            marcador="Nenhum cliente — modelo geral"
          />
        </div>
        <div className="form-linha">
          <label htmlFor="modelo-texto">Texto</label>
          <textarea
            id="modelo-texto" rows={3} value={form.texto}
            onChange={(e) => setForm((f) => ({ ...f, texto: e.target.value }))}
            placeholder="Ex.: Serviços de consultoria prestados no mês de competência."
          />
        </div>
        {erro && <p className="erro">{erro}</p>}
        <div className="botoes">
          <button type="button" onClick={salvar} disabled={salvando}>
            {salvando ? "Salvando..." : editandoId ? "Salvar alterações" : "Adicionar modelo"}
          </button>
          {editandoId && (
            <button type="button" className="secundario" onClick={cancelarEdicao}>
              Cancelar
            </button>
          )}
        </div>
      </div>
    </Modal>
  );
}
