# Emissão de NF-e modelo 55 (mercadorias)

Data: 2026-11-05

## Contexto

O sistema hoje só emite NFS-e (serviço, leiaute Nacional/municipal, via
`nfse_core`). A visão agora é adicionar emissão de **NF-e modelo 55**
(mercadorias, autorização pela SEFAZ do estado do emitente — não pela
prefeitura), reaproveitando o cadastro de empresa, usuário, certificado
digital A1 e o padrão de arquitetura já existentes (worker com polling
simples, sem Celery/Redis; XML guardado como `bytes` direto no Postgres;
PDF gerado on-demand, nunca persistido — ver `app/danfe.py` e
`app/routers/emissoes.py:228-316`, que é o padrão real hoje, não uma
suposição).

Motivação de negócio (sessão anterior): permitir cobrar um módulo
adicional das mesmas empresas clientes e, potencialmente, atrair cliente
novo que precise emitir nota de produto, não só de serviço.

## Objetivo

Empresa cadastrada no sistema consegue emitir NF-e modelo 55 pra um
destinatário, com itens de produto, cálculo de ICMS, autorização pela
SEFAZ da UF do emitente, download do XML autorizado e de um PDF
(DANFE), e cancelamento dentro do prazo. Mesma UI de empresa/certificado
de hoje; nova tela de cadastro de produto e nova tela de emissão.

## Fora de escopo (por ora)

- **Carta de Correção Eletrônica (CC-e)** — fica para depois do MVP.
- **Manifestação do destinatário** — não é obrigação do emitente.
- **NFC-e (modelo 65)** — documento de consumidor final, modelo e regras
  diferentes; não faz parte deste projeto.
- **Contingência SVC-AN/SVC-RS** (SEFAZ do estado fora do ar) — MVP trata
  como erro transitório com retentativa (reaproveita o backoff que já
  existe no worker pra NFS-e), sem implementar o fluxo formal de
  contingência ainda.
- **Inutilização de numeração** — caso raro (número pulado sem nunca ter
  sido submetido) e o fluxo normal de rejeição não o aciona (ver
  "Decisões já tomadas" sobre reenvio pós-rejeição). Fica fora do MVP;
  se precisar, a correção manual inicial é direto no banco/console,
  igual já é feito hoje pra ajustes raros de NFS-e.
- **Multi-UF simultâneo** — a tabela de endpoint por UF é construída de
  forma extensível, mas o piloto valida só a UF onde as empresas atuais
  já operam (Pará). Novas UFs entram sob demanda, uma por vez, cada uma
  precisando de homologação própria antes de produção.
- **Cobrança/billing deste módulo** (preço, plano, Asaas) — decisão de
  negócio separada, não faz parte deste documento técnico.
- **Importação de produtos em massa (planilha)** — cadastro de produto
  nasce manual pela UI; importação em lote é extensão futura se o volume
  justificar (mesmo padrão já usado pra Stone/CSV em NFS-e).

## Decisões já tomadas

- **Sem storage novo.** XML autorizado + protocolo fica como `bytes` em
  Postgres, igual a `Emissao.xml_nfse` hoje — não introduz S3 nem
  qualquer dependência de storage externo. Volume (algumas centenas de KB
  por nota) não justifica a complexidade extra, mesma lógica já aplicada
  à decisão de não usar Celery/Redis no worker.
- **DANFE gerado on-demand**, nunca persistido — mesmo padrão de
  `app/danfe.py`/`_gerar_pdf_bytes`: sempre que o cliente pedir o PDF, o
  sistema regenera a partir do XML autorizado guardado.
- **Certificado A1 reaproveitado** — é por CNPJ, não por módulo fiscal;
  nenhuma mudança em `Empresa.certificado_pfx_cifrado`.
- **Módulo novo `nfe_core`**, espelhando a estrutura de `nfse_core`
  (builder de XML, client de transporte, signer reaproveitado,
  catálogo de erros) — não mistura código de NF-e dentro de `nfse_core`.
- **Worker único, estendido** — `app/worker.py` passa a despachar por
  tipo de documento (`NFSE` vs `NFE`) em vez de ganhar um segundo loop
  separado; mesma tabela `emissoes` pode ganhar uma coluna
  `tipo_documento` ou (alternativa, ver "Pontos abertos") uma tabela
  separada `emissoes_nfe`.
- **Mesmo padrão de idempotência do NFS-e.** A chave de acesso da NF-e é
  determinística (UF+data+CNPJ+modelo+série+número+tpEmis+cNF+DV), igual
  o `dps_id` já é hoje — grava-se o id determinístico ANTES de chamar a
  SEFAZ e, se o worker cair no meio, consulta-se o protocolo antes de
  reenviar (mesmo mecanismo de `ja_submetida` que já existe em
  `worker.py`), evitando duplicidade. Nenhum mecanismo novo, só reaplicar
  o que já existe.
- **Reenvio após rejeição reaproveita a mesma série/número** — regra
  padrão do modelo NF-e (rejeição não "queima" o número, só autorização
  ou cancelamento/inutilização queimam), igual ao comportamento já
  implementado pra NFS-e (`_BACKOFF_REEMISSAO_AUTOMATICA` reenviando o
  mesmo `dps_id`). Nenhuma ramificação por `tipo_documento` necessária
  aqui. A validar ao vivo na Fase 1 (spike de homologação), mas não é
  esperado comportamento diferente por UF nesse ponto específico.

## Modelo de dados (proposta)

Novas colunas em `Empresa`:
- `inscricao_estadual: str | None`
- `crt: int | None` (Código de Regime Tributário — 1 Simples Nacional, 2
  Simples excesso sublimite, 3 Regime Normal)
- `uf: str(2) | None` (hoje só existe `municipio_ibge`; UF é derivável do
  código IBGE, mas like `Cliente.uf` já guarda explícito — manter
  consistência com o padrão que já existe em `Cliente`)

Nova tabela `produtos`:
- `id`, `empresa_id` (FK), `codigo_interno`, `descricao`, `ncm`,
  `cfop_padrao`, `unidade`, `cst_icms` ou `csosn_icms` (depende do CRT),
  `valor_unitario_padrao: Decimal | None`, `ativo: bool`, `criado_em`.

Nova tabela `emissoes_nfe` (separada de `emissoes`, não reaproveitada):
- Cabeçalho da NF-e: `empresa_id`, `cliente_id` (destinatário —
  reaproveita `Cliente`, que já tem `uf`/endereço completo), `serie`,
  `numero`, `chave_acesso`, `status` (mesmo enum `StatusEmissao`
  reaproveitado), `xml_nfe: bytes | None`, `protocolo_autorizacao`,
  `erros`, `resposta_bruta`, `criado_em`.

Nova tabela `itens_emissao_nfe`:
- `emissao_nfe_id` (FK), `produto_id` (FK), `quantidade`,
  `valor_unitario`, `valor_total`, `cfop` (pode sobrescrever o padrão do
  produto por emissão), + campos de imposto calculados por item
  (`valor_icms`, `base_icms`, etc.).

## Arquitetura

```
app/adapters/nfe_builder.py   — Empresa + Produto + itens -> NfeData (espelha dps_builder.py)
nfe_core/
  nfe.py                      — NfeData dataclass + build_nfe_xml() (espelha dps.py)
  client.py                   — SefazClient (SOAP), UF_ENDPOINTS (espelha SefinClient/MUNICIPIO_DPS_URLS)
  signer.py                   — reaproveita nfse_core/signer.py (assinatura XML-DSig é genérica)
  evento.py                   — cancelamento (espelha nfse_core/evento.py)
  error_catalog.py            — códigos de rejeição SEFAZ (c'c' Status vs cStat NF-e)
app/danfe_nfe.py               — gerar PDF a partir do XML autorizado (reportlab, igual danfe.py)
```

`app/worker.py` ganha um segundo ponto de entrada de processamento
(`processar_uma_pendente_nfe`) que roda no mesmo loop/processo, só
despachando pra `nfe_core` em vez de `nfse_core` quando a linha é de
`emissoes_nfe`.

## Fases de implementação

1. **Spike de homologação** — webservice SEFAZ-PA (autorização, consulta
   de protocolo, inutilização, cancelamento) em ambiente de homologação,
   com um certificado de teste; confirmar reuso do `nfse_core/signer.py`
   pra assinatura XML-DSig do padrão NF-e 4.00.
2. **Modelo de dados** — migração Alembic: colunas novas em `Empresa`,
   tabelas `produtos`, `emissoes_nfe`, `itens_emissao_nfe`.
3. **`nfe_core`** — `NfeData` + `build_nfe_xml()`, tabela `UF_ENDPOINTS`,
   `SefazClient` (autorização síncrona em lote — volume baixo não
   justifica lote assíncrono), consulta de protocolo, inutilização.
4. **Worker** — estender `app/worker.py` pra processar `emissoes_nfe`
   com o mesmo padrão de retentativa/backoff que já existe.
5. **Cálculo de imposto** — motor mínimo de ICMS por item (CST/CSOSN +
   CFOP + NCM informados manualmente no cadastro do produto; sem tabela
   de alíquota automática por NCM no MVP — alíquota vem do cadastro).
6. **DANFE** — `app/danfe_nfe.py`, gerado a partir do XML autorizado.
7. **Cancelamento** — evento de cancelamento (dentro do prazo da SEFAZ).
8. **Frontend** — cadastro de produto, tela de emissão (destinatário +
   itens), listagem/download de XML e PDF, diferenciação visual NFS-e
   vs NF-e no painel da empresa.
9. **Homologação ponta a ponta** com certificado de teste; depois piloto
   real com uma empresa.

## Pontos abertos (precisam de decisão)

- **Venda interestadual entra no MVP?** Se o destinatário (`Cliente`,
  que já guarda `uf`) puder ser de fora do Pará, o cálculo de imposto da
  Fase 5 precisa de DIFAL + FCP + partilha ICMS (EC 87/2015), não só
  CST/CFOP cadastrados manualmente no produto — isso muda o escopo da
  Fase 5 e possivelmente o cadastro de produto/cliente. Se o MVP for só
  venda dentro do Pará, a Fase 5 como descrita (alíquota vem do
  cadastro, sem tabela automática) é suficiente. **Esta é a decisão que
  mais pode estourar o escopo — preciso da sua resposta antes do plano
  de implementação.**
- Tabela `emissoes_nfe` separada vs. reaproveitar `emissoes` com uma
  coluna `tipo_documento` — a proposta acima escolhe tabela separada
  porque os campos de NF-e (itens, impostos) não têm equivalente em
  NFS-e e forçar isso em `emissoes` incharia o modelo; mas é uma
  escolha, não um fato.
- Biblioteca SOAP em Python pro client SEFAZ (`zeep` é a opção padrão do
  ecossistema; alternativa é montar o envelope SOAP manualmente como já
  é feito hoje pra REST no `nfse_core`).
- UF piloto: assumido Pará (onde as empresas atuais operam), a confirmar.
