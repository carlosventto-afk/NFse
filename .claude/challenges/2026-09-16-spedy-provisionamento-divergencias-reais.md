# Provisionamento na Spedy: divergências reais entre a doc pública e a API

Data: 2026-09-16

## Contexto

Depois de implementar a integração com a Spedy (plano
`docs/superpowers/plans/2026-09-15-spedy-integration.md`, 7 tasks + revisão
final, tudo baseado na documentação pública em `docs.spedy.com.br`), o
primeiro teste real em produção (empresa CNPJ 49055093000140, ambiente
homologação/sandbox) expôs **seis problemas reais**, nenhum previsto pela
documentação. Nenhum deles apareceu nos testes automatizados (que usam
`SpedyClient` mockado) — só surgiram ao bater na API de verdade.

Todos foram corrigidos, testados e commitados (`aebd33f`..`1676531`). Este
documento existe pra qualquer sessão futura que mexer nessa integração não
repetir a mesma sequência de descoberta.

## Método que funcionou

A cada erro genérico ("Bad Gateway", "HTTP 400"), em vez de só ler a doc de
novo, a estratégia mais eficaz foi:
1. Logar o corpo bruto da resposta da Spedy (não só a mensagem interpretada).
2. Reproduzir a MESMA chamada isolada, direto via `curl`, usando a chave de
   sandbox que o usuário já tinha (nunca inventar/assumir o formato).
3. Comparar o que a doc dizia vs o que a API realmente fazia.

Esse padrão (`curl` direto contra o sandbox real) resolveu em minutos coisas
que ficariam invisíveis só lendo a doc ou só olhando o traceback.

## Divergências confirmadas (doc pública vs comportamento real)

1. **`location` no payload de emissão** — doc sugere string
   (`"companyMunicipality"`/`"serviceProvisionMunicipality"`). Real: precisa
   ser objeto `{"code": "<ibge>"}`, igual ao campo `city`. String causa
   HTTP 400 ("Error converting value... to type CitySimpleDto").
   → `app/adapters/spedy_payload.py`.

2. **Resposta de `POST /companies`** — doc sugere `{"result": {...}}`. Real:
   campos direto na raiz (`id`, `apiCredentials`, etc.), sem wrapper.
   → `SpedyClient.criar_empresa` agora tolera os dois formatos.

3. **Formato de erro de validação** — doc (implícita) sugere
   `{"message": "..."}`. Real: `{"errors": [{"message": "...", "path": ...}]}`
   — mesmo formato usado nos erros de emissão/cancelamento, só que
   `_handle_estrito` (usado no provisionamento) nunca tinha sido atualizado
   pra reconhecer isso. Sem o fix, todo erro real virava um genérico
   "HTTP 400"/"HTTP 429" sem pista nenhuma.

4. **Autenticação do provisionamento** — doc sugere usar a `X-Api-Key` da
   empresa recém-criada (devolvida por `criar_empresa`) para os passos
   seguintes (`adicionar_certificado`, `configurar_nfse`). Real: **os três
   passos exigem a chave MESTRE** — a chave da empresa devolve 403 "Acesso
   não autorizado" nesses dois endpoints. A chave da empresa só serve pras
   operações de emissão/consulta/cancelamento (confirmado que essas sim
   usam a chave da empresa corretamente).

5. **CNPJ duplicado ("empresa órfã")** — qualquer tentativa de
   provisionamento que falhe DEPOIS de `criar_empresa` mas antes do fim do
   fluxo deixa uma empresa cadastrada na Spedy sem registro local
   correspondente (a chave dela nunca foi capturada — a Spedy só devolve a
   chave da empresa **uma vez**, na criação, sem endpoint pra recuperá-la
   depois). Toda nova tentativa esbarra em "O CNPJ já possui uma conta
   vinculada." até alguém apagar a órfã manualmente. Aconteceu de verdade
   **3 vezes** na mesma sessão de teste (causas diferentes: bug nosso, erro
   de dado, rate limit). Fix: `provisionar_empresa` agora detecta esse erro
   específico, localiza a órfã pelo CNPJ (`GET /companies`, filtrado do
   lado de cá — o filtro `federalTaxNumber` da query string não filtra de
   fato) e apaga+recria sozinho.

6. **Rate limit de rajada por segundo** — além do limite geral por minuto
   (exposto via `X-Rate-Limit-*`), existe um limite mais agressivo de
   chamadas por segundo. As 3-5 chamadas sequenciais do provisionamento
   (criar empresa, [apagar órfã,] subir certificado, configurar), feitas
   sem pausa, batiam HTTP 429 mesmo com sobra grande no limite por minuto —
   confirmado que a MESMA chamada, isolada, funcionava normalmente. Fix:
   `asyncio.sleep(1.0)` entre cada chamada do provisionamento.

## Bug nosso (não da Spedy) descoberto no meio do caminho

`SpedyClient.__init__` fixava `Content-Type: application/json` como header
padrão do `httpx.AsyncClient` inteiro. Isso funciona por coincidência nas
chamadas com `json=` (é exatamente o Content-Type que o httpx geraria
sozinho), mas **quebra silenciosamente** qualquer chamada com `files=`
(upload multipart, usado em `adicionar_certificado`): o corpo do request sai
multipart de verdade, mas o header mente "application/json", e o servidor
(ASP.NET) não consegue achar os campos — devolvendo "The Password field is
required" / "The CertificateFile field is required" mesmo com conteúdo
real e não-vazio (confirmado por log de diagnóstico antes de achar a causa).
Fix: nunca fixar `Content-Type` no cliente — deixar o httpx decidir por
chamada (`json=` → `application/json`, `files=` → `multipart/form-data;
boundary=...` automaticamente). Reproduzido e confirmado localmente com um
script de 5 linhas antes de mexer em produção de novo.

## Limite observado do plano sandbox

A conta sandbox (Plano Desenvolvedor) usada nos testes aceitou no máximo
**2 empresas simultâneas** — uma terceira tentativa (mesmo com CNPJ nunca
usado antes) devolveu a mesma mensagem "CNPJ já possui uma conta vinculada",
sugerindo que essa mensagem é reaproveitada tanto pra duplicata real quanto
pra limite de plano atingido. Não é um bloqueio pro uso normal (a conta real
do usuário provavelmente tem limite diferente), só um dado a considerar se
"criar mais uma empresa de teste" começar a falhar sem explicação.
