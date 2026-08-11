# NFS-e Nacional — kit de emissão em Python

Emissão, consulta e cancelamento de **NFS-e no padrão Nacional** (SEFIN / gov.br),
extraído de um sistema em produção que emite notas de verdade desde julho/2026.

Não é uma biblioteca genérica de "notas fiscais": é o caminho específico do
**Sistema Nacional NFS-e** — o padrão unificado que substitui os mil sistemas
municipais diferentes. Se o seu município já aderiu ao Nacional, isto emite. Se
ele ainda usa sistema próprio (Ginfes, ISSNet, WebISS...), isto **não** serve.

---

## Comece por aqui (3 minutos)

```bash
python -m venv .venv
# Windows:      .venv\Scripts\activate
# Linux/macOS:  source .venv/bin/activate

pip install -r requirements.txt
python exemplos/00_teste_local.py
```

O `00_teste_local.py` **não precisa de certificado nem de internet**. Ele gera um
certificado de teste, monta uma DPS, assina e confere a assinatura do mesmo jeito
que a SEFIN confere. Se ele imprimir `[OK] Tudo certo`, seu ambiente está pronto
e você já pode abrir o `dps_exemplo_assinada.xml` para ver o XML que sai daqui.

Depois: copie `.env.example` para `.env`, preencha, e rode
`python exemplos/01_emitir_nota.py`.

---

## O que tem aqui

```
nfse_core/          O núcleo. Sem banco, sem ORM, sem framework web.
  dps.py              monta o XML da DPS (a "nota" que você submete)
  signer.py           assina com certificado A1 (ICP-Brasil), padrão DF-e
  client.py           conversa com a SEFIN (mTLS + GZip + Base64)
  evento.py           monta o XML de cancelamento
  resposta.py         lê as respostas de forma tolerante a mudança de nome
  certificado.py      valida o A1: titular, CNPJ, validade, alerta de vencimento
  error_catalog.py    traduz os códigos de erro da SEFIN para português claro

exemplos/
  00_teste_local.py   valida seu ambiente — sem certificado, sem internet
  01_emitir_nota.py   emissão completa
  02_cancelar_nota.py cancelamento (evento e101101)
  03_consultar.py     consulta por chave, e por DPS (sua saída de emergência)

docs/
  ARMADILHAS.md       ⭐ LEIA. Os erros que custaram dias para descobrir.
  INTEGRACAO.md       Como plugar isto no seu sistema.
```

O fluxo inteiro de uma emissão:

```python
xml       = build_dps_xml(DpsData(...))          # monta
assinado  = sign_dps(xml, pfx_base64, senha)     # assina
bruta     = await SefinClient(ambiente, pfx_base64, senha).emitir_dps(assinado)
resultado = ler_resposta_emissao(bruta)          # lê (tolerante a mudança de nome)

if resultado.autorizada:
    guardar(resultado.chave_acesso, resultado.xml_nfse)   # o XML é o documento
else:
    mostrar(resultado.erros)                              # já traduzidos
```

O cancelamento é simétrico: `build_evento_cancelamento_xml` → `sign_evento` →
`registrar_evento` → `ler_resposta_evento`.

Tudo o que é do **seu** sistema — de onde vem o valor, quem é o tomador, onde a
emissão é gravada, quando ela dispara — fica fora do núcleo, de propósito.
Veja `docs/INTEGRACAO.md`.

---

## O que você precisa antes de emitir de verdade

1. **Certificado A1 (e-CNPJ) ICP-Brasil**, arquivo `.pfx` + senha. A1 é o de
   arquivo; A3 (token/cartão) **não** funciona aqui — a assinatura precisa da
   chave privada em memória.
2. **Inscrição Municipal** do prestador. Sem ela, erro `E0099`.
3. **Adesão do município ao Sistema Nacional.** Confira em
   <https://www.gov.br/nfse> antes de qualquer coisa. Município não aderido
   rejeita tudo com `E0084`/`E0099`, e nenhum ajuste de código resolve.
4. **Credenciamento na produção restrita** para testar. É um ambiente separado,
   com cadastro próprio.

---

## Avisos que valem tempo

- **Comece em `homologacao`.** Nota emitida em `producao` é documento fiscal
  real; cancelar depois envolve prazo municipal e justificativa.
- **O número da nota é sequencial e único por série.** Reenviar um número já
  usado é rejeitado. No seu sistema, isso precisa vir de um contador
  transacional no banco — nunca de um `max(numero) + 1` lido antes do commit.
- **Nunca comite o `.pfx`, a senha ou o `.env`.** O `.gitignore` já cobre, mas
  confira antes do primeiro push.
- **Guarde o XML autorizado.** Ele é o documento fiscal, não o PDF. O PDF
  (DANFSe) é só uma representação e pode ser regerado; o XML, não.

---

## Documentação oficial

- Portal: <https://www.gov.br/nfse>
- Leiautes e schemas XSD (ANEXO I = DPS, ANEXO II = eventos):
  <https://www.gov.br/nfse/pt-br/biblioteca/documentacao-tecnica/documentacao-atual>
- Manual da API "Contribuintes — Emissor Público"

A documentação oficial é incompleta em pontos importantes. O que falta nela
está em `docs/ARMADILHAS.md` — foi descoberto na tentativa e erro contra o
ambiente real.

---

## Licença e origem

Código extraído de um ERP em produção (TN Costa Tecnologia), compartilhado
diretamente com você pelo autor. Contém apenas a camada fiscal — nenhuma lógica
de negócio do sistema de origem. Combine com ele os termos de uso e
redistribuição; não há licença aberta declarada aqui.

Sem garantia: emissão de documento fiscal é responsabilidade de quem emite.
Valide em produção restrita e confira as regras do seu município antes de
emitir a primeira nota real.
