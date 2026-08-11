# Como plugar isto no seu sistema

O `nfse_core/` não conhece o seu banco, seu ORM nem seu framework. Ele faz três
coisas: monta o XML, assina e conversa com a SEFIN. O resto é seu.

Este documento descreve o que você precisa construir em volta — e o que é fácil
errar em cada parte.

---

## O mínimo que o seu sistema precisa ter

### 1. Onde guardar o certificado

O PFX é um segredo forte: quem o tem assina em nome da empresa. **Não guarde em
arquivo no servidor nem em texto puro no banco.**

A prática recomendada: cifrar em repouso com uma chave dedicada, separada da
chave geral da aplicação — se um segredo vazar, o outro continua protegendo. A
senha do PFX é cifrada junto.

```python
from cryptography.fernet import Fernet
# a chave vem de variável de ambiente, nunca do código
cifrado = Fernet(CHAVE).encrypt(pfx_base64.encode())
```

Guarde também a **data de validade** e avise antes de vencer. Certificado A1
dura 1 ano e a emissão para de funcionar sem aviso no dia seguinte.
`nfse_core.certificado` já faz isso:

```python
from nfse_core import inspecionar, conferir_titularidade

info = inspecionar(pfx_base64, senha)     # levanta CertificateError se inválido
info.titular          # "RAZAO SOCIAL LTDA:12345678000199"
info.cnpj             # "12345678000199"
info.valido_ate       # datetime
info.alerta           # mensagem pronta para a tela, ou None

conferir_titularidade(info, cnpj_do_prestador)   # avisa se for outro CNPJ
```

Chame `inspecionar()` **no upload**, antes de gravar: assim o arquivo errado ou
a senha errada são recusados na hora, e não na primeira emissão.

### 2. Contador de numeração

Precisa ser **transacional**. O padrão que funciona:

```sql
-- dentro da MESMA transação da emissão
UPDATE nfse_config
   SET proximo_numero = proximo_numero + 1
 WHERE id = :id
RETURNING proximo_numero - 1;
```

O `UPDATE ... RETURNING` trava a linha; duas emissões simultâneas serializam.
Ler com `SELECT` e depois gravar é o caminho da duplicata.

**Número queimado:** se a SEFIN rejeitar, você já consumiu o número. Não tente
reciclar — o padrão fiscal aceita buracos na sequência. Avance.

### 3. Registro da emissão

Uma tabela com, no mínimo:

| Campo | Por quê |
|---|---|
| `status` | pendente / autorizada / rejeitada / cancelada |
| `numero`, `serie` | a numeração consumida |
| `dps_id` | permite consultar a SEFIN se você perder a resposta |
| `chave_acesso` | 50 dígitos, identifica a nota autorizada |
| `xml_dps`, `xml_nfse` | **o XML autorizado é o documento fiscal** — guarde |
| `erros` | a lista traduzida, para a tela mostrar algo útil |
| `referencia_id` | o que originou a nota no SEU domínio (parcela, pedido, contrato) |

Grave a emissão como `pendente` **antes** de chamar a SEFIN. Se o processo
morrer no meio, você fica com um registro pendente e o `dps_id` para consultar —
sem isso, a nota pode existir na SEFIN e não existir no seu sistema.

### 4. O adaptador

É a única peça que mistura o seu domínio com o fiscal:

```python
def montar_dps(pedido, config) -> DpsData:
    return DpsData(
        tp_amb=1 if config.ambiente == "producao" else 2,
        dh_emi=datetime.now(BRT),
        serie=config.serie,
        numero=proximo_numero(config),          # transacional, item 2
        competencia=pedido.competencia,

        prest_cnpj=config.cnpj,
        prest_im=config.inscricao_municipal,
        c_loc_emi=config.municipio_ibge,
        op_simp_nac=config.regime,

        toma_cpf_cnpj=pedido.cliente.documento,
        toma_nome=pedido.cliente.nome,
        toma_email=pedido.cliente.email,

        c_trib_nac=config.codigo_tributacao,
        x_desc_serv=f"{pedido.descricao} - competencia {pedido.competencia:%m/%Y}",
        v_serv=pedido.valor,
    )
```

Repare que **só o adaptador conhece as duas coisas**. O núcleo não sabe o que é
um pedido; o seu domínio não sabe o que é uma DPS.

---

## Fluxo de emissão completo

```python
async def emitir(pedido, config):
    # 1. valida o que impede a emissão ANTES de consumir número
    if not config.certificado_cifrado:
        raise ValueError("Certificado nao configurado")
    if not pedido.cliente.documento:
        raise ValueError("Cliente sem CPF/CNPJ")

    # 2. consome o número e grava como pendente, na mesma transação
    emissao = registrar_pendente(pedido, numero=proximo_numero(config))

    # 3. monta, assina, envia
    pfx, senha = decifrar(config)
    dados = montar_dps(pedido, config)
    assinado = sign_dps(build_dps_xml(dados), pfx, senha)

    cliente = SefinClient(config.ambiente, pfx, senha)
    try:
        resposta = await cliente.emitir_dps(assinado)
    finally:
        await cliente.close()

    # 4. interpreta — `ler_resposta_emissao` absorve as variações de nome
    resultado = ler_resposta_emissao(resposta)
    if resultado.autorizada:
        emissao.marcar_autorizada(resultado.chave_acesso, resultado.xml_nfse)
    else:
        emissao.marcar_rejeitada(resultado.erros_json())
    return emissao
```

### Emissão em lote

Não faça em request HTTP síncrono. Cada nota leva alguns segundos e a SEFIN
oscila; 200 notas estouram qualquer timeout.

O padrão que funciona: uma tabela de job com progresso (total, processadas,
falhas) e processamento em background. Se o seu sistema já tem Celery, RQ ou
similar, use o que tem — o importante é não segurar a resposta HTTP.

**Commit por nota, não no fim do lote.** Se o processo morrer na nota 150, as
149 anteriores precisam estar salvas — senão você reemite todas e queima 149
números.

---

## O PDF da nota (DANFSe)

O PDF oficial vem da API do ADN:

```python
pdf = await SefinClient.fetch_danfse_pdf(ambiente, pfx, senha, chave_acesso)
if pdf is None:
    pdf = gerar_meu_pdf(emissao)   # fallback OBRIGATÓRIO — ver ARMADILHAS item 10
```

Ela devolve `None` em vez de levantar quando não responde (já tentou 4 vezes por
dentro). **Sempre tenha o fallback**: a API cai com frequência, e o operador não
pode ficar sem o documento por causa disso.

O que importa guardar é o **XML autorizado** — ele é o documento fiscal. O PDF é
representação e pode ser regerado a qualquer momento.

---

## Checklist antes da primeira nota real

- [ ] `00_teste_local.py` passou
- [ ] Município aderiu ao Sistema Nacional (confirmado em gov.br/nfse)
- [ ] Certificado A1 válido, com data de validade guardada e alerta configurado
- [ ] Inscrição Municipal preenchida
- [ ] Emissão limpa em `homologacao`
- [ ] Certificado cifrado em repouso, `.env` fora do git
- [ ] Contador de numeração transacional
- [ ] XML autorizado sendo persistido (não só o PDF)
- [ ] Registro `pendente` gravado antes da chamada à SEFIN
- [ ] Erros traduzidos aparecendo na tela para quem opera
