# ADR-0004 — Estrutura da interface (fase 1, incremento 1.2)

- **Data:** 02/11/2026
- **Status:** aceito

## Decisões

1. **Shell com menu lateral** (`presentation/shell.py`): páginas criadas sob demanda e recarregadas
   ao abrir; ao bloquear, o shell inteiro é destruído (D2/D8). Primeiro uso: formulário "Dados do
   consultório", que também cria as categorias padrão (pelo regime tributário) e a conta caixa.
2. **Workspace**: depois do desbloqueio, `bootstrap.build_app` monta os serviços sobre a conexão
   aberta do banco cifrado; as telas só falam com casos de uso.
3. **Tema claro explícito** (`apply_theme`): paleta própria. Achado: com o Windows em modo escuro, o
   estilo Fusion herdava cores escuras e deixava tabelas, combos e barra ilegíveis.
4. **`ValueCombo`**: o `QComboBox` converte os dados guardados (`StrEnum` → `str`), o que fazia o
   CNPJ válido ser recusado como "não corresponde ao tipo". Os valores ficam numa lista Python.
5. **Campo de valor (`MoneyEdit`)** digitado como app de banco, em centavos inteiros, sem `float`;
   colar aceita "1.234,56"; texto inválido colado é ignorado.
6. **"Ocultar valores"** (Ctrl+H, D8) passa pelo módulo único de formatação.

## Desvios conscientes das skills

- **MVVM:** cadastros simples (formulário ↔ entidade ↔ caso de uso) ficam numa página fina, sem view
  model separado. Telas com estado e regras de tela (lançamentos, 1.3) terão view model.
- **I/O na thread da UI:** operações curtas de banco local (CRUD, < 100 ms) rodam na thread da
  interface, por simplicidade e porque a conexão é única. Operações longas (importação, backup,
  relatórios grandes) vão para segundo plano. Revisar se alguma meta de `performance` for violada.

## Bug pego pelos testes

`FormDialog` guardava a ação de salvar em `self._save`, o mesmo nome do método das subclasses: o
atributo `None` escondia o método e o botão Salvar não fazia nada. Corrigido (`_save_handler`) e
agora a base falha alto se não houver ação configurada.
