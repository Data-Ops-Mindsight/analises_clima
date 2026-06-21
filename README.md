# Mapa de Calor — Pesquisa de Clima

Aplicação Streamlit para visualização de mapas de calor de pesquisas de clima organizacional.

## Acesso / Autenticação

O app exige login. As credenciais são configuradas localmente via `.streamlit/secrets.toml` (nunca versionado).

### Gerar hashes de senha

Edite `gerar_hash_senha.py`, coloque as senhas desejadas na lista `senhas` e execute:

```bash
python gerar_hash_senha.py
```

O script imprime o hash bcrypt de cada senha. Cole cada hash no campo `password` do `secrets.toml`.

### Configurar credenciais localmente

1. Copie o arquivo de exemplo:
   ```
   cp .streamlit/secrets.toml.example .streamlit/secrets.toml
   ```
2. Edite `.streamlit/secrets.toml`:
   - Troque `TROCAR_POR_CHAVE_ALEATORIA_LONGA_32_CHARS` por uma string aleatória longa (use `python -c "import secrets; print(secrets.token_hex(32))"`)
   - Substitua `COLAR_HASH_AQUI` pelos hashes gerados no passo anterior
   - Ajuste os nomes de usuário (`[credentials.usernames.<username>]`) conforme necessário

O `secrets.toml` está no `.gitignore` e nunca será commitado.

### Deploy no Streamlit Community Cloud

No painel do app em **Settings → Secrets**, cole todo o conteúdo do `secrets.toml` real. O app lê as credenciais via `st.secrets` em tempo de execução.

Para restringir o acesso apenas a e-mails autorizados, vá em **Settings → Sharing** e adicione os e-mails permitidos.

### Adicionar ou remover um usuário

Edite a seção `[credentials.usernames]` do `secrets.toml` (local) ou dos Secrets no Streamlit Cloud:

- **Adicionar**: insira um novo bloco `[credentials.usernames.<novo_usuario>]` com `name` e `password` (hash gerado pelo script).
- **Remover**: apague o bloco correspondente.

Após editar os secrets no Cloud, o app reinicia automaticamente.
