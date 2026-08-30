# Conectar o app ao Google Drive institucional (@ifmg.edu.br)

Isso faz o `lab_dados.db` ser salvo automaticamente numa pasta do seu
Google Drive institucional a cada novo registro — sem isso, o app funciona
normalmente, só que só com o arquivo local (sem backup na nuvem).

Leva uns 10 minutos e só precisa ser feito uma vez.

## Passo 1 — Criar um projeto e uma "conta de serviço" no Google Cloud

1. Acesse https://console.cloud.google.com/ (pode usar sua conta @ifmg.edu.br).
2. Crie um projeto novo (ex: "lab-aberto-fisica-app").
3. No menu, vá em **APIs e serviços → Biblioteca**, procure **Google Drive API**
   e clique em **Ativar**.
4. Vá em **APIs e serviços → Credenciais → Criar credenciais → Conta de serviço**.
   - Nome: algo como `lab-aberto-drive-sync`.
   - Não precisa dar nenhum papel/role especial no projeto — pode pular essa etapa.
5. Depois de criada, clique na conta de serviço → aba **Chaves** → **Adicionar
   chave → Criar nova chave → JSON**. Isso baixa um arquivo `.json` — guarde-o,
   ele é a credencial (é como uma senha, não compartilhe publicamente).
6. Anote o **e-mail da conta de serviço** (algo como
   `lab-aberto-drive-sync@lab-aberto-fisica-app.iam.gserviceaccount.com`) —
   você vai precisar dele no próximo passo.

## Passo 2 — Criar e compartilhar a pasta no seu Drive institucional

1. No seu Google Drive (@ifmg.edu.br), crie uma pasta, ex: `Lab Aberto de Física — Dados`.
2. Clique com o botão direito → **Compartilhar** → cole o e-mail da conta de
   serviço (do passo 1.6) → dê permissão de **Editor**.
3. Abra a pasta e copie o ID dela na URL:
   `https://drive.google.com/drive/folders/AQUI_ESTA_O_ID` → copie só a parte
   depois de `/folders/`.

Isso garante exatamente o que está no projeto aprovado pelo CEP: os dados
ficam numa pasta institucional, com acesso restrito (só você e essa conta
de serviço têm acesso — ninguém mais entra sem que você compartilhe).

## Passo 3 — Configurar os secrets no Streamlit

**Se for rodar localmente:** crie um arquivo `.streamlit/secrets.toml` na
mesma pasta do `app.py`, com este conteúdo (preencha com os dados do seu
arquivo JSON baixado no passo 1.5, e o ID da pasta do passo 2.3):

```toml
gdrive_folder_id = "COLE_O_ID_DA_PASTA_AQUI"

[gdrive_service_account]
type = "service_account"
project_id = "SEU_PROJECT_ID"
private_key_id = "..."
private_key = "-----BEGIN PRIVATE KEY-----\n...\n-----END PRIVATE KEY-----\n"
client_email = "lab-aberto-drive-sync@....iam.gserviceaccount.com"
client_id = "..."
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "..."
```

Todos esses campos já estão no arquivo `.json` que você baixou — é só
copiar cada valor para o campo correspondente. **Nunca suba esse arquivo
secrets.toml pro GitHub** (adicione `.streamlit/secrets.toml` no seu
`.gitignore`).

**Se for publicar no Streamlit Cloud:** no painel do app, vá em
**Settings → Secrets** e cole o mesmo conteúdo TOML acima diretamente lá
(o Streamlit Cloud guarda isso de forma criptografada, não vai pro repositório).

## Pronto

Na próxima vez que abrir o app, a barra lateral vai mostrar
"☁️ Nuvem institucional conectada", e cada observação/avaliação salva
some sincronizada automaticamente com essa pasta do Drive. Tem também um
botão "🔄 Sincronizar agora" na barra lateral, caso queira forçar manualmente.
