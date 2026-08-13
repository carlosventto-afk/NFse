import { useEffect, useState, type FormEvent } from "react";
import { atualizarCliente, criarCliente, listarClientes } from "../api/clientes";
import type { Cliente, ClienteForm } from "../api/types";

const VAZIO: ClienteForm = {
  cpf_cnpj: "", nome: "", email: "", telefone: "", inscricao_estadual: "",
  inscricao_municipal: "", logradouro: "", numero: "", complemento: "",
  bairro: "", municipio_ibge: "", uf: "", cep: "",
};

function normalizar(dados: ClienteForm): ClienteForm {
  const limpo = { ...dados } as unknown as Record<string, string | boolean | null | undefined>;
  Object.keys(limpo).forEach((chave) => {
    if (limpo[chave] === "") {
      limpo[chave] = null;
    }
  });
  return limpo as unknown as ClienteForm;
}

export default function ClientesPage() {
  const [clientes, setClientes] = useState<Cliente[]>([]);
  const [editando, setEditando] = useState<Cliente | null>(null);
  const [form, setForm] = useState<ClienteForm>(VAZIO);
  const [erro, setErro] = useState<string | null>(null);
  const [carregando, setCarregando] = useState(true);

  async function carregar() {
    setCarregando(true);
    const lista = await listarClientes();
    setClientes(lista);
    setCarregando(false);
  }

  useEffect(() => {
    carregar();
  }, []);

  function iniciarEdicao(cliente: Cliente) {
    setEditando(cliente);
    const { id: _id, ...resto } = cliente;
    setForm(resto);
  }

  function iniciarNovo() {
    setEditando(null);
    setForm(VAZIO);
  }

  function atualizarCampo(campo: keyof ClienteForm, valor: string) {
    setForm((atual) => ({ ...atual, [campo]: valor }));
  }

  async function salvar(evento: FormEvent) {
    evento.preventDefault();
    setErro(null);
    try {
      if (editando) {
        await atualizarCliente(editando.id, { ...normalizar(form), ativo: editando.ativo });
      } else {
        await criarCliente(normalizar(form));
      }
      iniciarNovo();
      await carregar();
    } catch (e) {
      setErro(e instanceof Error ? e.message : "Nao foi possivel salvar o cliente");
    }
  }

  async function alternarAtivo(cliente: Cliente) {
    const { id, ...resto } = cliente;
    await atualizarCliente(id, { ...resto, ativo: !cliente.ativo });
    await carregar();
  }

  return (
    <div>
      <h1>Clientes</h1>
      <form onSubmit={salvar} className="cartao" style={{ margin: 0, marginBottom: "1.5rem" }}>
        <h2>{editando ? `Editando ${editando.nome}` : "Novo cliente"}</h2>
        <div className="form-linha">
          <label htmlFor="nome">Nome</label>
          <input id="nome" required value={form.nome ?? ""} onChange={(e) => atualizarCampo("nome", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="cpf_cnpj">CPF/CNPJ</label>
          <input id="cpf_cnpj" value={form.cpf_cnpj ?? ""} onChange={(e) => atualizarCampo("cpf_cnpj", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="email">E-mail</label>
          <input id="email" value={form.email ?? ""} onChange={(e) => atualizarCampo("email", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="telefone">Telefone</label>
          <input id="telefone" value={form.telefone ?? ""} onChange={(e) => atualizarCampo("telefone", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="ie">Inscricao estadual</label>
          <input id="ie" value={form.inscricao_estadual ?? ""} onChange={(e) => atualizarCampo("inscricao_estadual", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="im">Inscricao municipal</label>
          <input id="im" value={form.inscricao_municipal ?? ""} onChange={(e) => atualizarCampo("inscricao_municipal", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="logradouro">Logradouro</label>
          <input id="logradouro" value={form.logradouro ?? ""} onChange={(e) => atualizarCampo("logradouro", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="numero">Numero</label>
          <input id="numero" value={form.numero ?? ""} onChange={(e) => atualizarCampo("numero", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="complemento">Complemento</label>
          <input id="complemento" value={form.complemento ?? ""} onChange={(e) => atualizarCampo("complemento", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="bairro">Bairro</label>
          <input id="bairro" value={form.bairro ?? ""} onChange={(e) => atualizarCampo("bairro", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="municipio_ibge">Codigo IBGE do municipio</label>
          <input id="municipio_ibge" value={form.municipio_ibge ?? ""} onChange={(e) => atualizarCampo("municipio_ibge", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="uf">UF</label>
          <input id="uf" maxLength={2} value={form.uf ?? ""} onChange={(e) => atualizarCampo("uf", e.target.value)} />
        </div>
        <div className="form-linha">
          <label htmlFor="cep">CEP</label>
          <input id="cep" value={form.cep ?? ""} onChange={(e) => atualizarCampo("cep", e.target.value)} />
        </div>
        {erro && <p className="erro">{erro}</p>}
        <button type="submit">{editando ? "Salvar alteracoes" : "Criar cliente"}</button>
        {editando && <button type="button" className="secundario" onClick={iniciarNovo}>Cancelar edicao</button>}
      </form>

      {carregando ? (
        <p>Carregando...</p>
      ) : (
        <table>
          <thead>
            <tr>
              <th>Nome</th><th>CPF/CNPJ</th><th>E-mail</th><th>Ativo</th><th></th>
            </tr>
          </thead>
          <tbody>
            {clientes.map((cliente) => (
              <tr key={cliente.id}>
                <td>{cliente.nome}</td>
                <td>{cliente.cpf_cnpj ?? "-"}</td>
                <td>{cliente.email ?? "-"}</td>
                <td>{cliente.ativo ? "Sim" : "Nao"}</td>
                <td>
                  <button className="secundario" onClick={() => iniciarEdicao(cliente)}>Editar</button>
                  <button className={cliente.ativo ? "perigo" : ""} onClick={() => alternarAtivo(cliente)}>
                    {cliente.ativo ? "Inativar" : "Reativar"}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
}
