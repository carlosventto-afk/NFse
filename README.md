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
6. Cadastre a primeira empresa: `python scripts/criar_empresa.py --cnpj ... --pfx caminho/certificado.pfx ...` (veja `--help`)
7. `uvicorn app.main:app --reload` — API em `http://localhost:8000`
8. Em outro terminal, rode o worker: `python -c "import asyncio; from app.db import SessionLocal; from app.worker import loop_worker; asyncio.run(loop_worker(SessionLocal))"`

## Rodando os testes

```bash
pytest -v
```

Exige o Postgres do `docker compose` no ar (banco `nfse_test`).

## Checklist antes da primeira nota real (fora do automatizável por teste)

- [ ] `python nfse-nacional-kit/nfse-nacional-kit/exemplos/00_teste_local.py` — smoke test do núcleo fiscal, sem rede.
- [ ] **Confirmar contra a SEFIN Nacional real (homologação) que a emissão sem documento do tomador é aceita** — o ajuste da Task 7 replica o que a prefeitura de Belém/PA aceitou, mas isso nunca foi testado contra o validador do Sistema Nacional. Se for rejeitado, o fallback é coletar o documento antes de emitir (ex: reativar um formulário de complemento no portal) — mas só decida isso depois do teste real, não antes.
- [ ] Confirmar o código de tributação nacional (6 dígitos) exato para "14.10 — Tinturaria e lavanderia" contra a tabela oficial de desdobros do ANEXO — `141001` usado nos testes deste plano é um palpite baseado no padrão observado, não uma fonte oficial.
- [ ] Cadastro de parceiro Stone aprovado (`partner.stone.com.br/formulario`) e webhook real recebido pelo menos uma vez em ambiente de teste — confirmar nomes de campo exatos do payload real; se o CPF/CNPJ do tomador vier disponível, é uma melhoria simples ajustar `app/adapters/stone.py` para preenchê-lo (não é obrigatório, já que a emissão funciona sem ele).
- [ ] Confirmar em <https://www.gov.br/nfse> que o município aderiu ao Sistema Nacional.
- [ ] Emissão limpa em `homologacao` (produção restrita) com o certificado A1 real da empresa.
- [ ] Só depois de uma emissão limpa em homologação, trocar `Empresa.ambiente` para `producao`.
