import { useEffect, useMemo, useState, type FormEvent } from "react";
import { Link } from "react-router-dom";
import { criarCliente, listarClientes } from "../api/clientes";
import { emitirManual } from "../api/emissoes";
import { listarModelosDescricao } from "../api/modelosDescricao";
import type { Cliente, ModeloDescricao } from "../api/types";
import ComboBox from "../components/ComboBox";
import GerenciarModelosModal from "../components/GerenciarModelosModal";

const SERVICO_VAZIO = { descricao: "", valor: "", competencia: "" };
const NOVO_CLIENTE_VAZIO = { nome: "", cpf_cnpj: "", email: "" };

function formatarDocumento(doc: string | null): string | undefined {
  if (!doc) return undefined;
  return doc.length > 11
    ? doc.replace(/(\d{2})(\d{3})(\d{3})(\d{4})(\d{2})/, "$1.$2.$3/$4-$5")
    : doc.replace(/(\d{3})(\d{3})(\d{3})(\d{2})/, "$1.$2.$3-$4");
}

export default function EmissaoAvulsaPage() {
  const [clientes, setClientes] = useState<Cliente[]>([]);
  const [modelos, setModelos] = useState<ModeloDescricao[]>([]);
  const [carregando, setCarregando] = useState(true);

  const [clienteId, setClienteId] = useState<string | null>(null);
  const [servico, setServico] = useState(SERVICO_VAZIO);

  const [mostrarNovoCliente, setMostrarNovoCliente] = useState(false);
  const [novoCliente, setNovoCliente] = useState(NOVO_CLIENTE_VAZIO);
  const [salvandoCliente, setSalvandoCliente] = useState(false);

  const [mostrarModelos, setMostrarModelos] = useState(false);

  const [enviando, setEnviando] = useState(false);
  const [erro, setErro] = useState<string | null>(null);
  const [sucesso, setSucesso] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([listarClientes(), listarModelosDescricao()])
      .then(([clientesCarregados, modelosCarregados]) => {
        setClientes(clientesCarregados);
        setModelos(modelosCarregados);
      })
      .catch(() => {
        setErro("Não foi possível carregar clientes e modelos de descrição.");
      })
      .finally(() => setCarregando(false));
  }, []);

  const clienteSelecionado = clientes.find((c) => c.id === clienteId) ?? null;

  // Modelo vinculado ao cliente vem primeiro na lista -- e e o que preenche
  // a descricao automaticamente ao escolher o cliente (ver efeito abaixo).
  const modelosOrdenados = useMemo(
    () =>
      [...modelos].sort((a, b) => {
        const aVinculado = a.cliente_id === clienteId && clienteId !== null;
        const bVinculado = b.cliente_id === clienteId && clienteId !== null;
        if (aVinculado !== bVinculado) return aVinculado ? -1 : 1;
        return a.titulo.localeCompare(b.titulo);
      }),
    [modelos, clienteId],
  );

  function selecionarCliente(id: string | null) {
    setClienteId(id);
    if (!id) return;
    // So preenche sozinho se a descricao ainda estiver vazia -- nao
    // sobrescreve o que a pessoa ja digitou.
    if (servico.descricao.trim()) return;
    const modeloDoCliente = modelos.find((m) => m.cliente_id === id);
    if (modeloDoCliente) {
      setServico((s) => ({ ...s, descricao: modeloDoCliente.texto }));
    }
  }

  function aplicarModelo(modeloId: string | null) {
    if (!modeloId) return;
    const modelo = modelos.find((m) => m.id === modeloId);
    if (modelo) setServico((s) => ({ ...s, descricao: modelo.texto }));
  }

  async function salvarNovoCliente() {
    if (!novoCliente.nome.trim()) {
      setErro("Informe o nome do cliente.");
      return;
    }
    setErro(null);
    setSalvandoCliente(true);
    try {
      const criado = await criarCliente({
        nome: novoCliente.nome.trim(),
        cpf_cnpj: novoCliente.cpf_cnpj.trim() || null,
        email: novoCliente.email.trim() || null,
        telefone: null, inscricao_estadual: null, inscricao_municipal: null,
        logradouro: null, numero: null, complemento: null, bairro: null,
        municipio_ibge: null, uf: null, cep: null,
      });
      setClientes((atual) => [...atual, criado].sort((a, b) => a.nome.localeCompare(b.nome)));
      setClienteId(criado.id);
      setMostrarNovoCliente(false);
      setNovoCliente(NOVO_CLIENTE_VAZIO);
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível cadastrar o cliente");
    } finally {
      setSalvandoCliente(false);
    }
  }

  async function enviar(evento: FormEvent) {
    evento.preventDefault();
    if (!clienteId || !clienteSelecionado) {
      setErro("Selecione o cliente que vai receber a nota.");
      return;
    }
    setErro(null);
    setSucesso(null);
    setEnviando(true);
    try {
      const emissao = await emitirManual({
        cpf_cnpj: clienteSelecionado.cpf_cnpj ?? "",
        nome: clienteSelecionado.nome,
        email: clienteSelecionado.email ?? "",
        descricao: servico.descricao,
        valor: servico.valor,
        competencia: servico.competencia,
      });
      setSucesso(`Nota ${emissao.serie}/${emissao.numero} criada e enviada para emissão.`);
      // Mantem competencia (comum emitir varias notas seguidas na mesma
      // competencia) e limpa cliente/descricao -- fluxo pensado pra digitar
      // nota apos nota sem reabrir a tela.
      setClienteId(null);
      setServico((atual) => ({ ...SERVICO_VAZIO, competencia: atual.competencia }));
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Não foi possível criar a emissão");
    } finally {
      setEnviando(false);
    }
  }

  return (
    <div className="pagina-emissao">
      <h1>Emissão avulsa</h1>
      <p className="ajuda">
        Alternativa à importação de planilha — para empresas que não vendem por esse fluxo.
        A nota entra na fila normal de emissão (mesma usada pelo resto do sistema); acompanhe
        o status em <Link to="/emissoes">Emissões</Link>.
      </p>

      <form onSubmit={enviar}>
        <section className="secao-emissao">
          <h2>Tomador</h2>
          <div className="form-linha">
            <label htmlFor="cliente">Cliente</label>
            <ComboBox
              id="cliente"
              itens={clientes.map((c) => ({
                id: c.id, rotulo: c.nome, subRotulo: formatarDocumento(c.cpf_cnpj),
              }))}
              valorId={clienteId}
              aoSelecionar={selecionarCliente}
              marcador={carregando ? "Carregando clientes..." : "Buscar cliente por nome ou CPF/CNPJ"}
              rotuloNovo="+ Cadastrar novo cliente"
              aoClicarNovo={() => { setClienteId(null); setMostrarNovoCliente(true); }}
            />
          </div>

          {clienteSelecionado && (
            <div className="resumo-tomador">
              <div className="resumo-tomador-dados">
                <strong>{clienteSelecionado.nome}</strong>
                <span>
                  {formatarDocumento(clienteSelecionado.cpf_cnpj) ?? "Sem CPF/CNPJ cadastrado"}
                  {clienteSelecionado.email && ` · ${clienteSelecionado.email}`}
                </span>
              </div>
              <button type="button" className="secundario" onClick={() => setClienteId(null)}>
                Trocar
              </button>
            </div>
          )}

          {mostrarNovoCliente && (
            <div className="expansor">
              <div className="linha-campos">
                <div className="form-linha">
                  <label htmlFor="novo-cliente-nome">Nome</label>
                  <input
                    id="novo-cliente-nome" autoFocus value={novoCliente.nome}
                    onChange={(e) => setNovoCliente((c) => ({ ...c, nome: e.target.value }))}
                  />
                </div>
                <div className="form-linha">
                  <label htmlFor="novo-cliente-doc">CPF/CNPJ (opcional)</label>
                  <input
                    id="novo-cliente-doc" value={novoCliente.cpf_cnpj}
                    onChange={(e) => setNovoCliente((c) => ({ ...c, cpf_cnpj: e.target.value }))}
                  />
                </div>
              </div>
              <div className="form-linha">
                <label htmlFor="novo-cliente-email">E-mail (opcional)</label>
                <input
                  id="novo-cliente-email" type="email" value={novoCliente.email}
                  onChange={(e) => setNovoCliente((c) => ({ ...c, email: e.target.value }))}
                />
              </div>
              <div className="botoes">
                <button type="button" onClick={salvarNovoCliente} disabled={salvandoCliente}>
                  {salvandoCliente ? "Salvando..." : "Salvar cliente"}
                </button>
                <button
                  type="button" className="secundario"
                  onClick={() => { setMostrarNovoCliente(false); setNovoCliente(NOVO_CLIENTE_VAZIO); }}
                >
                  Cancelar
                </button>
              </div>
              <p className="ajuda">
                Endereço e inscrições ficam para depois — complete em Clientes se precisar.
              </p>
            </div>
          )}
        </section>

        <section className="secao-emissao">
          <div className="rotulo-com-acao">
            <h2>Serviço</h2>
            <button type="button" className="link-acao" onClick={() => setMostrarModelos(true)}>
              Gerenciar modelos
            </button>
          </div>

          <div className="form-linha">
            <label htmlFor="modelo">Modelo de descrição (opcional)</label>
            <ComboBox
              id="modelo"
              itens={modelosOrdenados.map((m) => ({
                id: m.id, rotulo: m.titulo,
                subRotulo: m.cliente_id === clienteId && clienteId ? "deste cliente" : undefined,
              }))}
              valorId={null}
              aoSelecionar={aplicarModelo}
              marcador="Escolher um modelo para preencher a descrição"
            />
          </div>

          <div className="form-linha">
            <label htmlFor="descricao">Descrição do serviço</label>
            <textarea
              id="descricao" required rows={3} value={servico.descricao}
              onChange={(e) => setServico((s) => ({ ...s, descricao: e.target.value }))}
            />
          </div>
        </section>

        <section className="secao-emissao">
          <h2>Valores</h2>
          <div className="linha-campos">
            <div className="form-linha">
              <label htmlFor="valor">Valor (R$)</label>
              <input
                id="valor" required inputMode="decimal" value={servico.valor}
                onChange={(e) => setServico((s) => ({ ...s, valor: e.target.value }))}
              />
            </div>
            <div className="form-linha">
              <label htmlFor="competencia">Competência</label>
              <input
                id="competencia" type="date" required value={servico.competencia}
                onChange={(e) => setServico((s) => ({ ...s, competencia: e.target.value }))}
              />
            </div>
          </div>
        </section>

        {erro && <p className="erro">{erro}</p>}
        {sucesso && <p>{sucesso}</p>}
        <button type="submit" disabled={enviando}>{enviando ? "Enviando..." : "Emitir"}</button>
      </form>

      {mostrarModelos && (
        <GerenciarModelosModal
          modelos={modelos}
          clientes={clientes}
          aoFechar={() => setMostrarModelos(false)}
          aoAtualizarModelos={setModelos}
        />
      )}
    </div>
  );
}
