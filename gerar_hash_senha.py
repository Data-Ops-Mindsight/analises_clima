# Gera hashes bcrypt para senhas usadas no secrets.toml.
# Uso: python gerar_hash_senha.py
# Cole os hashes gerados nos campos "password" do seu .streamlit/secrets.toml.

import streamlit_authenticator as stauth

senhas = [
    # Adicione quantas senhas quiser:
    "senha_do_cliente",
    "senha_do_admin",
]

hashes = stauth.Hasher.hash_list(senhas)

for senha, h in zip(senhas, hashes):
    print(f"{senha!r:30s}  ->  {h}")
