# Primeira emissão real em produção via Spedy (Belém): cadeia de 4 rejeições

Data: 2026-10-05
Empresa de referência: CNPJ 49055093000140, Belém/PA (IBGE 1501402), Simples
Nacional, item LC116 14.10 (lavanderia).

## Contexto

Depois do provisionamento inicial na Spedy (ver
`2026-09-16-spedy-provisionamento-divergencias-reais.md`), a primeira
sequência real de tentativas de emissão em **produção** (não sandbox) expôs
4 problemas diferentes, um de cada vez — cada fix revelava o próximo erro,
nunca o mesmo erro genérico se repetindo. Este documento existe pra uma
sessão futura reconhecer os sintomas e já saber o fix, em vez de reabrir a
investigação do zero.

## Ordem real dos sintomas (cada um só apareceu depois do anterior ser corrigido)

### 1. `SPD999` — "Erro ao estabelecer comunicação com o serviço" (recorrente em homologação E produção)

Sintoma enganoso: parecia erro de payload (testamos `federalServiceCode` no
formato LC116 com ponto em vez do cTribNac de 6 dígitos, removemos
`cnaeCode`, removemos o bloco `receiver` inteiro — nenhuma dessas mudanças
fez diferença no SPD999 em si, embora o fix do `federalServiceCode` fosse
correto por outro motivo, ver `app/adapters/spedy_payload.py`).

**Causa real**: nada a ver com payload. A homologação funcionava (autorizava
notas de teste) mas produção dava SPD999 sempre — ou seja, o cadastro da
empresa **especificamente em produção** na Spedy estava desatualizado/
inconsistente (homologação e produção são contas/chaves mestras separadas
lá, cada uma com seu próprio provisionamento).

**Fix**: checkbox "Forçar reprovisionamento na Spedy" em Editar Empresa
(`forcar_reprovisionamento_spedy`, ver `app/routers/empresas.py`) — reusa o
certificado já salvo, roda `provisionar_empresa` do zero (que já trata CNPJ
duplicado apagando a empresa órfã e recriando). Resolveu tanto o SPD999
quanto, de brinde, um "Usuário não autenticado" que apareceu antes dele
(`alterar_empresa`/`habilitar_reforma_tributaria` só aceitam a chave MESTRE,
nunca a da própria empresa — mesmo padrão já documentado pro resto do
provisionamento).

### 2. `L0022` — "A série informada na DPS deve estar dentro da faixa reservada para esse fim (de 10001 a 49999)"

**Causa**: série `"1"` (= 00001) é reservada ao sistema **municipal próprio**
de geração de NFS-e. Quem emite por fora (API/integrador) precisa de série
entre 10001 e 49999 — padrão do leiaute Nacional NFS-e, não só de Belém.

**Fix**: `Empresa.serie` default mudou de `"1"` pra `"10001"`
(`app/models.py`) — evita a mesma rejeição na primeira emissão de QUALQUER
empresa nova daqui pra frente. Empresa já existente com série fora da faixa
precisa trocar manualmente em "Numeração" (nota: trocar a série reinicia a
numeração — comece em 1 na série nova, sem conflito com a antiga).

### 3. `E0316` — "Código da lista NBS informado inexistente tabela de NBS do sistema"

**Causa**: o leiaute Nacional NFS-e (reforma tributária) exige o código NBS
(Nomenclatura Brasileira de Serviços) além do `federalServiceCode` (LC116).
A Spedy aceita o campo `nbsCode` como entrada em `POST /service-invoices`,
mas **não deriva ele sozinha** a partir do `federalServiceCode` — sem mandar
explicitamente, a prefeitura rejeita.

**Fix**: campo `Empresa.nbs_code`, configurável em "Editar empresa", enviado
em `payload["nbsCode"]` quando preenchido (`app/adapters/spedy_payload.py`).
Valor certo por empresa vem da tabela oficial de correlação LC116→NBS
(Anexo VIII, `gov.br/nfse/.../documentacao-tecnica/rtc`) — pra item 14.10
(lavanderia/limpeza de têxteis) é **`1.2601.10.00`**. Não adivinhar esse
valor — cada atividade tem o seu.

### 4. Armadilha de processo (não é código): campo cadastrado mas não salvo

Depois do fix do item 3, a emissão ainda saía sem `nbsCode` no payload — o
deploy tinha funcionado, mas o campo "Código NBS" em Editar Empresa nunca
tinha sido preenchido/salvo de fato. **Sempre conferir o `requisicao_bruta`
real antes de assumir que um fix de cadastro "não funcionou"** — muitas
vezes é só o dado que falta preencher, não o código.

## Resultado final confirmado

Com reprovisionamento forçado + série 10001 + NBS `1.2601.10.00`
preenchidos, a emissão passou de todos os 4 bloqueios. Método que funcionou
em todos os casos: pedir pro usuário mandar o par requisição/resposta bruta
(`REQUISICAO_*.json`/`RESPOSTA_*.json`, já baixáveis pela tela de Emissões)
em vez de tentar adivinhar pela mensagem de erro sozinha.

## Pendências conhecidas

- O valor de NBS é fixo por cadastro de empresa hoje (um único
  `Empresa.nbs_code`) — se uma empresa algum dia prestar mais de um tipo de
  serviço (itens LC116 diferentes), isso não escala; reavaliar se/quando
  aparecer esse caso.
- `receiver` continua removido do payload (ver comentário em
  `spedy_payload.py`) — nunca foi restaurado nem comprovadamente necessário
  depois que o SPD999 real (item 1 acima) foi resolvido por outro motivo.
  Se precisar mandar dados do tomador de novo, reavaliar com cuidado (já
  houve uma vez em que a ausência desse bloco pareceu causar SPD999 — pode
  ter sido coincidência com o problema de cadastro de produção).
