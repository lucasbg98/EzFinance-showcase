# Processo de release

Ferramenta: `packaging/release.py` (sempre via `uv run python packaging/release.py …`).

## Chaves e estado do repositório de atualizações

| O quê | Onde | Versionado? |
|---|---|---|
| Chaves privadas TUF (root, targets, snapshot, timestamp) | `APPFIN_RELEASE_HOME\keys` (padrão `%USERPROFILE%\.appfin-release-test`) | **Nunca** |
| Repositório TUF (metadados assinados + pacotes) | `APPFIN_RELEASE_HOME\repository` | Não (é publicado na hospedagem) |
| `root.json` confiável (público) | `src/appfin/resources/tuf_root.json` | Sim — vai dentro do app |

> ⚠️ **As chaves atuais são de TESTE** (sem senha). 🗣️ Decisão de 02/11/2026: **adiado** — gerar as
> chaves de produção depois dos testes neste PC e antes da primeira instalação real no consultório:
> 1. `APPFIN_RELEASE_HOME=<pasta nova> uv run python packaging/release.py keys --encrypted`
>    (pede senha para root e targets).
> 2. Commitar o novo `tuf_root.json`.
> 3. Copiar a pasta `keys` para **2 pen drives cifrados** (BitLocker To Go) guardados em locais
>    diferentes. Depois de publicar, a chave **root** deve ficar só offline.
> Perder a chave root = não conseguir mais publicar atualizações confiáveis (exigiria reinstalar o app).

## Passo a passo de uma versão

1. Atualizar a versão em `src/appfin/__init__.py` **e** `pyproject.toml`; atualizar o `CHANGELOG.md`.
2. Rodar o checklist de segurança (`docs/PROJETO.md` §7.13). O CI precisa estar verde.
3. `uv run python packaging/release.py build` → executável, **autoteste do .exe**, instalador e SHA-256
   em `dist/installer/`.
4. Testar numa VM/Windows Sandbox: instalação limpa **e** atualização a partir da versão anterior.
5. `uv run python packaging/release.py publish` → assina e publica no repositório TUF.
6. Enviar `repository/metadata` e `repository/targets` para a hospedagem (ver pendência abaixo).
7. Publicar o instalador + `.sha256` (release privada do GitHub) e criar a tag `vX.Y.Z`.

## Manutenção periódica

- **Mensal:** `release.py refresh` e reenviar os metadados. O `timestamp` vence em 30 dias; vencido,
  o app apenas deixa de encontrar atualizações (falha segura) até a renovação.
- **Anual:** renovar o `root` (vence em 365 dias) com a chave root offline.

## Hospedagem das atualizações — decidido: Supabase Storage (fase 2)

🗣️ Decisão de 02/11/2026: os metadados e pacotes assinados ficarão num **bucket público do Supabase
Storage**, configurado junto com a nuvem na **fase 2**. O bucket só guarda arquivos já assinados
(nenhum dado do consultório); a segurança vem das assinaturas TUF, não do sigilo do bucket. Escrita no
bucket só pelo mantenedor (nunca pelo app). Até lá, a atualização automática fica desligada.

Opções que foram avaliadas (o cliente precisa baixar `metadata/` e `targets/` **sem login**; os anexos
do repositório privado do GitHub não servem):

| Opção | Custo | Observação |
|---|---|---|
| Bucket público do **Supabase Storage** (já previsto na fase 2) | grátis | Só pacotes e metadados assinados; nenhum dado |
| Repositório **público separado** só com os arquivos de atualização (+ GitHub Pages) | grátis | O executável fica público (não contém segredos, por projeto) |
| Cloudflare R2 / S3 público | ~grátis | Mais um fornecedor |

Até decidir, a URL fica vazia em `updater.py` (`DEFAULT_UPDATE_URL`) e a atualização automática fica
desligada. Atualizações manuais continuam possíveis instalando o novo instalador por cima.

## Teste local de ponta a ponta (já executado em 02/11/2026)

`release.py serve` serve o repositório em `http://127.0.0.1:8765`. Com o app instalado e
`APPFIN_UPDATE_URL=http://127.0.0.1:8765`, a versão antiga detecta a nova, pede confirmação,
bloqueia, troca os arquivos e reabre na versão nova, preservando o desinstalador e os dados.
