# Mapa de Calor — Pesquisa de Clima

Aplicação Streamlit para visualização de mapas de calor de pesquisas de clima organizacional.

## Acesso / Autenticação

O app exige login. As credenciais são configuradas via `.streamlit/secrets.toml` (nunca versionado).

### Formato exato do secrets.toml

```toml
[cookie]
name = "clima_auth"
key = "CHAVE_ALEATORIA_LONGA_MIN_32_CHARS"
expiry_days = 7

[credentials.usernames.nome_do_usuario]
name = "Nome Completo"
password = "$2b$12$HASH_BCRYPT_AQUI"
```

- O `name` do usuário é o que aparece em "Logado como: ..." na sidebar.
- O `password` deve ser um hash bcrypt gerado com `gerar_hash_senha.py` (não coloque senha em texto puro).
- Adicione quantos blocos `[credentials.usernames.<usuario>]` quiser.
- **Não adicione campos extras** (`email`, `roles`, etc.) a menos que queira usá-los; a lib trata campos ausentes com `.get()`.

### Gerar hashes de senha

Edite `gerar_hash_senha.py` com as senhas desejadas e execute:

```bash
python gerar_hash_senha.py
```

O script imprime o hash bcrypt de cada senha. Cole no campo `password` do `secrets.toml`.

### Configurar credenciais localmente

1. Copie o arquivo de exemplo:
   ```
   copy .streamlit\secrets.toml.example .streamlit\secrets.toml
   ```
2. Gere uma chave para o cookie:
   ```bash
   python -c "import secrets; print(secrets.token_hex(32))"
   ```
3. Gere os hashes das senhas com `gerar_hash_senha.py`.
4. Preencha o `secrets.toml` com a chave e os hashes.

O `secrets.toml` está no `.gitignore` e nunca será commitado.

### Deploy no Streamlit Community Cloud

Em **Settings → Secrets**, cole o conteúdo completo do `secrets.toml` real. O app lê via `st.secrets` em tempo de execução.

Para restringir o acesso por e-mail: **Settings → Sharing → Invite viewers by email**.

### Adicionar ou remover um usuário

Edite a seção `[credentials.usernames]` no `secrets.toml` local ou nos Secrets do Cloud:

- **Adicionar**: insira um novo bloco `[credentials.usernames.<novo_usuario>]` com `name` e `password` (hash gerado pelo script).
- **Remover**: apague o bloco correspondente.

Após editar os secrets no Cloud, o app reinicia automaticamente.
