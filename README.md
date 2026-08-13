# NFS-e Automatizada — Stone webhook

Emite NFS-e Nacional automaticamente a partir de pagamentos aprovados na
Stone, com portal para consulta, download e emissão manual. Ver desenho
completo em `docs/superpowers/specs/2026-08-11-nfse-stone-webhook-design.md`.

## Rodando localmente

1. `docker compose up -d db`
2. `docker compose exec db psql -U nfse -d nfse -c "CREATE DATABASE nfse_test;"`
3. Copie `.env.example` para `.env` e preencha `FERNET_KEY`/`JWT_SECRET` (comandos no próprio `.env.example`).
4. `pip install -r requirements-dev.txt`
5. `alembic upgrade head`
6. Cadastre o primeiro ADM da plataforma e um plano diretamente no banco
   (não há UI para isso ainda), depois convide um titular
   (`POST /convites` com `plano_id`), aceite o convite
   (`POST /convites/aceitar`), e só então cadastre a empresa:
   `python scripts/criar_empresa.py --cnpj ... --pfx caminho/certificado.pfx
   --titular-email titular@empresa.com ...` (veja `--help`)
7. `uvicorn app.main:app --reload` — API em `http://localhost:8000/api`
   (rotas de negócio) e `http://localhost:8000/health` (health check, sem
   prefixo). O frontend (plano separado) espera exatamente esse prefixo.
8. Em outro terminal, rode o worker: `python -c "import asyncio; from app.db import SessionLocal; from app.worker import loop_worker; asyncio.run(loop_worker(SessionLocal))"`
9. Frontend em dev: `cd frontend && npm install && npm run dev` — abre em
   `http://localhost:5173`, com proxy para a API em `8000`.
10. Frontend em produção: `cd frontend && npm run build` — o FastAPI passa
    a servir `frontend/dist/` automaticamente em `/` quando esse diretório
    existir (nenhuma configuração adicional).

## Rodando os testes

```bash
pytest -v
```

Exige o Postgres do `docker compose` no ar (banco `nfse_test`).

## Checklist antes da primeira nota real (fora do automatizável por teste)

- [ ] Cadastrar ao menos um `Plano` (tabela `planos`) e um usuário com
  `eh_admin_plataforma=true` diretamente no banco antes do primeiro uso —
  não há endpoint para isso ainda (é o primeiro operador humano da
  plataforma; convites exigem alguém já com essa permissão).
- [ ] `python nfse-nacional-kit/nfse-nacional-kit/exemplos/00_teste_local.py` — smoke test do núcleo fiscal, sem rede.
- [ ] **Bloco `<end>` de endereço do tomador (`nfse_core/dps.py`) é uma
  extensão sem precedente no kit vendorizado** — precisa ser confirmado
  contra a documentação oficial ou um envio de teste em homologação antes
  de qualquer emissão real vir a usá-lo (hoje nada em `app/` o aciona
  ainda).
- [ ] **Confirmar contra a SEFIN Nacional real (homologação) que a emissão sem documento do tomador é aceita** — o ajuste da Task 7 replica o que a prefeitura de Belém/PA aceitou, mas isso nunca foi testado contra o validador do Sistema Nacional. Se for rejeitado, o fallback é coletar o documento antes de emitir (ex: reativar um formulário de complemento no portal) — mas só decida isso depois do teste real, não antes.
- [ ] **`regApTribSN` (regime de apuração do Simples Nacional) ainda NÃO é configurável** — `app/adapters/dps_builder.py` nunca preenche `DpsData.reg_ap_trib_sn`, e o próprio `nfse_core/dps.py` documenta o campo como "obrigatório quando opSimpNac=3". A empresa deste projeto está cadastrada com `op_simp_nac=3` (optante ME/EPP), ou seja, cai exatamente nesse caso. A lacuna vem do exemplo incompleto do kit vendorizado, não desta implementação, e fechá-la de verdade exige uma coluna nova em `Empresa` (mudança de schema + migração) — tarefa própria, não um ajuste de última hora. **Antes da primeira emissão real com `op_simp_nac=3`, essa mudança precisa estar feita** (ou a DPS ir sem um campo que o leiaute exige). Se a empresa for MEI (`op_simp_nac=2`) ou não optante (`1`), o campo não se aplica e nada muda.
- [ ] Confirmar o código de tributação nacional (6 dígitos) exato para "14.10 — Tinturaria e lavanderia" contra a tabela oficial de desdobros do ANEXO — `141001` usado nos testes deste plano é um palpite baseado no padrão observado, não uma fonte oficial.
- [ ] Cadastro de parceiro Stone aprovado (`partner.stone.com.br/formulario`) e webhook real recebido pelo menos uma vez em ambiente de teste — confirmar nomes de campo exatos do payload real; se o CPF/CNPJ do tomador vier disponível, é uma melhoria simples ajustar `app/adapters/stone.py` para preenchê-lo (não é obrigatório, já que a emissão funciona sem ele).
- [ ] Confirmar em <https://www.gov.br/nfse> que o município aderiu ao Sistema Nacional.
- [ ] Emissão limpa em `homologacao` (produção restrita) com o certificado A1 real da empresa.
- [ ] Só depois de uma emissão limpa em homologação, trocar `Empresa.ambiente` para `producao`.
