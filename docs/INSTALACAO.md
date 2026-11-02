# Instalação no computador do consultório

## Antes de instalar

1. **BitLocker ligado** no disco do Windows (Configurações → Privacidade e segurança → Criptografia do
   dispositivo / BitLocker). Protege os dados se o computador for roubado.
2. **Uma conta do Windows só para quem usa o app**, com senha. Não use conta de administrador no dia a dia.
3. Windows atualizado e Microsoft Defender ativo.

## Conferir o instalador (ainda sem assinatura digital)

O instalador ainda não tem assinatura Authenticode (decisão do projeto), então o Windows pode mostrar
"O Windows protegeu o computador". **Antes** de clicar em "Mais informações → Executar assim mesmo",
confira se o arquivo é o original:

```powershell
Get-FileHash .\AppFinanceiro-Setup-X.Y.Z.exe -Algorithm SHA256
```

O resultado precisa ser **idêntico** ao do arquivo `AppFinanceiro-Setup-X.Y.Z.exe.sha256` publicado
junto com a versão. Se for diferente, **não instale**.

## Instalar

- Execute o instalador (não precisa de administrador). O app vai para
  `%LOCALAPPDATA%\Programs\AppFinanceiro`.
- No primeiro uso: criar a **senha mestra** e anotar a **chave de recuperação em papel**. Guarde o
  papel fora do computador (ex.: cofre do consultório). Sem a senha **e** sem a chave, os dados não
  podem ser recuperados por ninguém.

## Onde ficam os dados

| O quê | Onde |
|---|---|
| Banco de dados cifrado, cofre (`vault.json`), logs | `%APPDATA%\AppFinanceiro` |
| Cache de atualizações | `%LOCALAPPDATA%\AppFinanceiro\updates` |

Desinstalar **não apaga** os dados. Nunca apague o `vault.json` sem um backup: sem ele o banco não abre.

## Atualizações

Depois do desbloqueio o app verifica se há versão nova (quando a hospedagem estiver configurada) e
**pergunta** antes de instalar. Só pacotes assinados pelo mantenedor são aceitos.
