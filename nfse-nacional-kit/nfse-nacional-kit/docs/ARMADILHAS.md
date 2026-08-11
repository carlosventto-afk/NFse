# Armadilhas do NFS-e Nacional

Este é o documento mais valioso do kit. Cada item abaixo custou horas ou dias
contra o ambiente real, e **nenhum deles está claro na documentação oficial**.

Se você só for ler uma coisa, leia as três primeiras.

---

## 1. C14N 2.0, não 1.0 — a causa mais comum do `E0714`

`E0714` diz "erro na assinatura". Sua assinatura pode estar matematicamente
perfeita e ainda assim tomar `E0714`, porque a SEFIN recalcula o digest sobre
uma forma canônica diferente da que você usou.

```python
# ERRADO — lxml método "c14n" (C14N 1.0): digest DIVERGE do da SEFIN
etree.tostring(element, method="c14n")

# CERTO — C14N 2.0, com re-serialização standalone antes
etree.canonicalize(etree.tostring(element).decode()).encode()
```

A re-serialização (`tostring` antes do `canonicalize`) é parte da receita, não
enfeite: ela reproduz o contexto de namespace que o validador usa.

Medido em 15/07/2026 contra `SefinNacional_1.6.0`, produção restrita.

**Por que não usar a lib `signxml`:** ela calcula o `DigestValue` sobre uma forma
canônica diferente da serialização final. Aqui o digest é computado por
construção sobre a MESMA árvore que é enviada. Já tentamos; não use.

## 2. Acento em campo de texto também vira `E0714`

Um travessão (`—`) na descrição do serviço derrubou uma emissão real. O
validador decodifica campos texto de forma divergente e o digest não bate.

A prática consolidada no ecossistema DF-e é **emitir sem acento**. O
`_sanitize_text()` do `dps.py` já faz isso: transliteração para ASCII, incluindo
pontuação tipográfica (aspas curvas, travessão, reticências, espaço fino).

Se você montar algum campo texto por fora, passe pelo `_sanitize_text` também.

## 3. A URL **não** leva `/API`

```
CERTO:  https://sefin.nfse.gov.br/SefinNacional
ERRADO: https://sefin.nfse.gov.br/API/SefinNacional
```

A página de documentação mostra o caminho com `/API/`. Esse caminho roteia para
um gateway com **validador divergente**, que devolve `E0714` para assinatura
correta. O caminho sem `/API` é o que os integradores homologados usam.

---

## 4. `Signature` sem prefixo de namespace (`E1228`)

```xml
<!-- CERTO -->
<Signature xmlns="http://www.w3.org/2000/09/xmldsig#">

<!-- ERRADO -->
<ds:Signature xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
```

E só o **certificado folha** no `KeyInfo` — não mande a cadeia inteira.

## 5. SHA-1, e não é escolha sua

RSA-SHA1 é exigência do padrão DF-e. Não "modernize" para SHA-256: a SEFIN
rejeita.

## 6. Cancelamento: a raiz é `pedRegEvento`, não `evento` (`E1235`)

A API espera o **pedido de registro** como raiz do XML submetido, e assina-se o
`infPedReg` (não o `infEvento`). O `evento` completo — com `nSeqEvento`,
`ambGer`, `nDFSe`, `dhProc` — é o artefato que o Sistema Nacional **constrói ao
redor** do seu pedido e devolve.

É simétrico ao par DPS → NFS-e: você submete a DPS, o sistema gera a NFS-e.

Isso não está em manual nem swagger oficial. Foi deduzido do `E1235`.

## 7. Os nomes das chaves JSON mudam entre request e response

No cancelamento:

| Direção  | Chave                             |
|----------|-----------------------------------|
| Request  | `pedidoRegistroEventoXmlGZipB64`  |
| Response | `eventoXmlGZipB64`                |

Confirmado em SDKs de referência, não documentado. E os nomes variam entre
versões do manual em geral — **leia a resposta de forma tolerante**, aceitando
variações de nome e de caixa (`Codigo`/`codigo`/`Código`). O `error_catalog.py`
já faz isso.

## 8. `E0712` — ME/EPP não pode usar `indTotTrib`

Se `opSimpNac=3` (optante ME/EPP), o campo `indTotTrib` é rejeitado. Tem que
mandar o detalhamento em percentual:

```xml
<pTotTrib>
  <pTotTribFed>0.00</pTotTribFed>
  <pTotTribEst>0.00</pTotTribEst>
  <pTotTribMun>0.00</pTotTribMun>
</pTotTrib>
```

O `dps.py` já ramifica por `op_simp_nac`.

## 9. Zeros à esquerda só no `Id`

`serie` e `nDPS` vão **sem** zeros não significativos (manual §6.1.1.d). O
`zfill` aparece só na montagem do `Id` da DPS (45 caracteres):

```
"DPS" + cLocEmi(7) + tpInscricao(1) + inscrição(14) + série(5) + número(15)
```

## 10. A API do DANFSe (PDF oficial) cai — insista

O PDF oficial vem do **ADN**, domínio diferente do SEFIN. Em produção real ela
devolve `502` de forma intermitente: já houve caso de 2 tentativas falharem e a
3ª trazer o PDF.

Uma tentativa só é otimista demais. O `client.py` tenta 4 vezes com espera
crescente e devolve `None` em vez de levantar — **sempre tenha um fallback que
gera a sua própria representação em PDF** a partir dos dados da nota. O sistema
de origem deste kit faz exatamente isso em produção.

## 11. Certificado A3 não funciona

A1 (arquivo `.pfx`) é obrigatório. A3 (token/smartcard) não serve: a assinatura
precisa da chave privada acessível em memória, e o A3 não a exporta.

## 12. Numeração: contador transacional, não `max() + 1`

Número duplicado é rejeitado. Ler `max(numero)` e somar 1 **fora de uma
transação** produz duplicata sob concorrência — duas emissões simultâneas leem o
mesmo valor.

Se a DPS foi enviada e você não sabe se virou nota, **não reenvie às cegas**:
`GET /dps/{id}` devolve a chave de acesso se já existir (é a saída de
idempotência da própria SEFIN).

---

## Catálogo de erros conhecidos

`error_catalog.py` traduz estes códigos para título + explicação + ação
sugerida. Não existe tabela oficial publicada com todos os códigos — este
catálogo foi construído a partir dos erros realmente encontrados.

| Código | O que é                                                        |
|--------|----------------------------------------------------------------|
| E0008  | Data/hora de emissão no futuro (relógio do servidor adiantado)  |
| E0084  | CNPJ sem estabelecimento no município nesta competência         |
| E0099  | Prestador não cadastrado no município (CNC) — falta a IM        |
| E0120  | Município não aderiu ao Sistema Nacional                        |
| E0202  | DPS duplicada (número já usado)                                 |
| E0712  | `indTotTrib` indevido para ME/EPP (ver item 8)                  |
| E0714  | Erro na assinatura (ver itens 1, 2 e 3 — quase sempre é um deles) |
| E1235  | Estrutura do pedido de evento incorreta (ver item 6)            |
| E3317  | Alíquota incompatível com o regime                              |
| E999   | Erro interno da SEFIN — tente de novo                           |

Código desconhecido cai num fallback que mostra o código e a descrição originais,
sem inventar explicação.

---

## Ordem sugerida para o primeiro sucesso

1. `python exemplos/00_teste_local.py` — valida o ambiente, sem rede.
2. Confirme que **seu município aderiu** ao Nacional.
3. Credencie-se na **produção restrita**.
4. `python exemplos/01_emitir_nota.py` com `NFSE_AMBIENTE=homologacao`.
5. Só depois de uma emissão limpa em homologação, mude para `producao`.

Se travar no `E0714`, releia os itens 1, 2 e 3 nesta ordem. É quase sempre um
deles.
