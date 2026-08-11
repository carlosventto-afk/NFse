# CLAUDE.md — kit NFS-e Nacional

Contexto para assistentes de IA trabalhando neste repositório.

## O que é

Núcleo de emissão de **NFS-e no padrão Nacional** (SEFIN / gov.br), extraído de
um sistema em produção. Não é biblioteca genérica de nota fiscal: é o caminho
específico do Sistema Nacional NFS-e. Municípios com sistema próprio (Ginfes,
ISSNet, WebISS) **não** são atendidos por este código.

Python 3.11+. Três dependências: `lxml`, `cryptography`, `httpx`. Sem framework,
sem ORM, sem banco.

## Antes de mexer em qualquer coisa

**Leia `docs/ARMADILHAS.md` por inteiro.** Este código tem várias decisões que
parecem erradas e não são — foram medidas contra o ambiente real da SEFIN. As
mais importantes:

| Parece errado | Por que está certo |
|---|---|
| `etree.canonicalize` em vez de `method="c14n"` | C14N 1.0 produz digest divergente do da SEFIN → `E0714` |
| RSA-**SHA1** | Exigência do padrão DF-e. SHA-256 é rejeitado |
| Assinador manual em vez de `signxml` | `signxml` digere uma forma canônica diferente da serialização final |
| Texto transliterado para ASCII | Acento em campo texto dispara `E0714` |
| URL sem `/API` | O caminho `/API/` da doc roteia para um gateway com validador divergente |
| Cancelamento assina `infPedReg`, não `infEvento` | A API espera o PEDIDO como raiz (`E1235`) |
| Leitura tolerante dos nomes de campo do JSON | Os nomes mudam entre versões do manual e entre request/response |

Os comentários no código explicam cada uma, com a data da medição. **Não
"simplifique" nenhuma delas sem reproduzir contra a produção restrita** — o
teste local não pega essas divergências, porque quem diverge é o validador do
outro lado.

## Estrutura

```
nfse_core/          núcleo genérico — não deve ganhar dependência de banco/web
  dps.py            monta o XML da DPS (DpsData → bytes)
  signer.py         assinatura XMLDSig com PFX
  client.py         HTTP mTLS contra a SEFIN
  evento.py         XML de cancelamento
  resposta.py       leitura tolerante das respostas da SEFIN
  certificado.py    inspeção do A1 (titular, CNPJ, validade)
  error_catalog.py  tradução dos códigos de erro
exemplos/           scripts que rodam de verdade
docs/               ARMADILHAS.md (leia) e INTEGRACAO.md
```

## Regra de ouro do núcleo

`nfse_core/` **não importa nada de fora dele** além de `lxml`, `cryptography` e
`httpx`. Se uma mudança precisar de banco, sessão HTTP, usuário logado ou
qualquer conceito de domínio, ela pertence ao adaptador do sistema hospedeiro,
não aqui. Ver `docs/INTEGRACAO.md`.

## Como validar uma mudança

1. `python exemplos/00_teste_local.py` — assinatura confere localmente (rápido,
   sem rede, sem certificado). Pega erro de estrutura e de assinatura própria.
2. Emissão real em `NFSE_AMBIENTE=homologacao` (produção restrita). **Só isto
   pega divergência de validador** — que é a classe de bug mais cara aqui.

Nunca considere uma mudança no `signer.py` ou no `dps.py` validada só pelo
passo 1.

## Segurança

- O PFX e a senha **nunca** entram no repositório, em log ou em mensagem de
  erro. O `.gitignore` cobre `*.pfx`, `*.pem`, `.env`, `*.b64.txt`.
- No sistema hospedeiro, cifre o PFX em repouso com chave dedicada (separada da
  chave da aplicação).
- Emitir nota em `producao` cria documento fiscal real. Em qualquer teste ou
  demonstração, use `homologacao`.

## Idioma

Código, comentários e documentação em **português do Brasil**. Nomes de
variável/função podem ficar em inglês quando espelham o leiaute oficial
(`tpAmb`, `cLocEmi`, `vServ` etc.) — esses vêm do XSD e não devem ser
traduzidos.
