"""
Laboratório Aberto de Física — Coleta e Análise de Dados
Digitaliza a Ficha de Observação Estruturada e a Rubrica de Avaliação
de Produções dos Estudantes, com dashboard de análise integrado.

Como rodar localmente:
    pip install -r requirements.txt
    streamlit run app.py

Para publicar no Streamlit Cloud, suba este arquivo + requirements.txt
para um repositório GitHub, do mesmo jeito que os outros trackers.

ARMAZENAMENTO: os dados ficam em um arquivo SQLite local (lab_dados.db) e,
se as credenciais do Google Drive estiverem configuradas (ver SETUP_DRIVE.md),
o app sincroniza automaticamente esse arquivo com uma pasta do Google Drive
institucional (@ifmg.edu.br) a cada novo registro — em linha com o que consta
no projeto aprovado pelo CEP (item 7.6): "dados anonimizados por meio de
códigos, armazenados em nuvem institucional com acesso restrito à
pesquisadora". Sem essa configuração, o app funciona normalmente, mas apenas
com armazenamento local (sem backup automático).
"""

import io
import streamlit as st
import pandas as pd
import sqlite3
import plotly.express as px
import plotly.graph_objects as go
from datetime import date, datetime
from pathlib import Path

try:
    from google.oauth2 import service_account
    from googleapiclient.discovery import build
    from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload
    GDRIVE_LIBS_OK = True
except ImportError:
    GDRIVE_LIBS_OK = False

# ------------------------------------------------------------------
# Config geral
# ------------------------------------------------------------------
st.set_page_config(
    page_title="Laboratório Aberto de Física — Coleta de Dados",
    page_icon="🔬",
    layout="wide",
)

DB_PATH = Path(__file__).parent / "lab_dados.db"

NIVEL_LABELS = {1: "1 — Baixo", 2: "2 — Médio", 3: "3 — Alto"}

RUBRICA = {
    "Aplicação de conceitos físicos": {
        3: "Utiliza corretamente conceitos físicos, com explicações coerentes e fundamentadas",
        2: "Apresenta conceitos parcialmente corretos, com pequenas inconsistências",
        1: "Apresenta erros conceituais ou ausência de fundamentação",
    },
    "Desenvolvimento investigativo": {
        3: "Formula hipóteses, controla variáveis e interpreta resultados de forma consistente",
        2: "Demonstra tentativa de investigação, com limitações metodológicas",
        1: "Não evidencia processo investigativo estruturado",
    },
    "Resolução de problemas": {
        3: "Propõe soluções claras, coerentes e bem justificadas",
        2: "Propõe soluções parciais ou pouco justificadas",
        1: "Não apresenta solução ou apresenta solução incoerente",
    },
    "Comunicação científica": {
        3: "Apresenta ideias com clareza, organização e linguagem adequada",
        2: "Apresenta organização parcial ou linguagem pouco precisa",
        1: "Apresenta dificuldades de organização e expressão",
    },
    "Autonomia": {
        3: "Atua de forma independente, toma decisões e propõe caminhos",
        2: "Apresenta alguma autonomia, mas depende de orientação",
        1: "Depende fortemente de orientação para realizar as atividades",
    },
}
CRITERIOS = list(RUBRICA.keys())

# ------------------------------------------------------------------
# Sincronização com Google Drive institucional
# ------------------------------------------------------------------
DRIVE_SCOPES = ["https://www.googleapis.com/auth/drive.file"]


def drive_enabled() -> bool:
    """Verifica se as credenciais do Drive foram configuradas em st.secrets."""
    if not GDRIVE_LIBS_OK:
        return False
    try:
        return "gdrive_service_account" in st.secrets and "gdrive_folder_id" in st.secrets
    except Exception:
        return False


def _get_drive_service():
    creds_info = dict(st.secrets["gdrive_service_account"])
    creds = service_account.Credentials.from_service_account_info(creds_info, scopes=DRIVE_SCOPES)
    return build("drive", "v3", credentials=creds)


def _find_drive_file_id(service, folder_id: str, filename: str):
    query = f"name = '{filename}' and '{folder_id}' in parents and trashed = false"
    results = service.files().list(q=query, fields="files(id, name)").execute()
    files = results.get("files", [])
    return files[0]["id"] if files else None


def download_db_from_drive() -> bool:
    """Baixa o lab_dados.db mais recente do Drive, se existir. Usado ao iniciar o app."""
    if not drive_enabled():
        return False
    try:
        service = _get_drive_service()
        folder_id = st.secrets["gdrive_folder_id"]
        file_id = _find_drive_file_id(service, folder_id, DB_PATH.name)
        if file_id is None:
            return False
        request = service.files().get_media(fileId=file_id)
        fh = io.FileIO(DB_PATH, "wb")
        downloader = MediaIoBaseDownload(fh, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        fh.close()
        return True
    except Exception as e:
        st.session_state["drive_error"] = str(e)
        return False


def upload_db_to_drive() -> bool:
    """Envia o lab_dados.db atual para a pasta do Drive, criando ou atualizando o arquivo."""
    if not drive_enabled():
        return False
    try:
        service = _get_drive_service()
        folder_id = st.secrets["gdrive_folder_id"]
        file_id = _find_drive_file_id(service, folder_id, DB_PATH.name)
        media = MediaIoBaseUpload(io.FileIO(DB_PATH, "rb"), mimetype="application/x-sqlite3", resumable=True)
        if file_id:
            service.files().update(fileId=file_id, media_body=media).execute()
        else:
            metadata = {"name": DB_PATH.name, "parents": [folder_id]}
            service.files().create(body=metadata, media_body=media, fields="id").execute()
        st.session_state["last_sync"] = datetime.now()
        st.session_state["drive_error"] = None
        return True
    except Exception as e:
        st.session_state["drive_error"] = str(e)
        return False


# ------------------------------------------------------------------
# Banco de dados
# ------------------------------------------------------------------
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db():
    conn = get_conn()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS observacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT, turma TEXT, atividade TEXT, grupo_codigo TEXT,
            participacao_ativa TEXT, engajamento TEXT,
            colaboracao TEXT, comunicacao_grupo TEXT,
            formula_hipoteses TEXT, controle_variaveis TEXT, interpretacao_resultados TEXT,
            iniciativa TEXT, tomada_decisao TEXT,
            observacoes_qualitativas TEXT,
            criado_em TEXT
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS avaliacoes (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT, turma TEXT, atividade TEXT, aluno_codigo TEXT,
            aplicacao_conceitos INTEGER, obs_aplicacao_conceitos TEXT,
            desenvolvimento_investigativo INTEGER, obs_desenvolvimento_investigativo TEXT,
            resolucao_problemas INTEGER, obs_resolucao_problemas TEXT,
            comunicacao_cientifica INTEGER, obs_comunicacao_cientifica TEXT,
            autonomia INTEGER, obs_autonomia TEXT,
            observacoes_gerais TEXT,
            criado_em TEXT
        )
    """)
    conn.commit()
    conn.close()


def insert_observacao(row: dict):
    conn = get_conn()
    cols = ", ".join(row.keys())
    placeholders = ", ".join("?" * len(row))
    conn.execute(f"INSERT INTO observacoes ({cols}) VALUES ({placeholders})", list(row.values()))
    conn.commit()
    conn.close()


def insert_avaliacao(row: dict):
    conn = get_conn()
    cols = ", ".join(row.keys())
    placeholders = ", ".join("?" * len(row))
    conn.execute(f"INSERT INTO avaliacoes ({cols}) VALUES ({placeholders})", list(row.values()))
    conn.commit()
    conn.close()


def load_df(table: str) -> pd.DataFrame:
    conn = get_conn()
    df = pd.read_sql(f"SELECT * FROM {table}", conn, parse_dates=["data"])
    conn.close()
    return df


def delete_row(table: str, row_id: int):
    conn = get_conn()
    conn.execute(f"DELETE FROM {table} WHERE id = ?", (row_id,))
    conn.commit()
    conn.close()


if "db_pulled" not in st.session_state:
    if drive_enabled() and not DB_PATH.exists():
        download_db_from_drive()
    st.session_state["db_pulled"] = True

init_db()

# ------------------------------------------------------------------
# Sidebar / navegação
# ------------------------------------------------------------------
st.sidebar.title("🔬 Lab Aberto de Física")
pagina = st.sidebar.radio(
    "Navegar",
    ["📝 Nova Observação", "📋 Nova Avaliação de Produção", "📊 Dashboard", "🗂️ Dados brutos"],
)

st.sidebar.divider()
if drive_enabled():
    if st.session_state.get("drive_error"):
        st.sidebar.error("⚠️ Erro ao sincronizar com o Drive")
        st.sidebar.caption(st.session_state["drive_error"])
    else:
        st.sidebar.success("☁️ Nuvem institucional conectada")
        last_sync = st.session_state.get("last_sync")
        if last_sync:
            st.sidebar.caption(f"Última sincronização: {last_sync.strftime('%d/%m %H:%M')}")
    if st.sidebar.button("🔄 Sincronizar agora", use_container_width=True):
        if upload_db_to_drive():
            st.sidebar.success("Sincronizado!")
else:
    st.sidebar.warning("💾 Rodando apenas local — sem backup no Drive")
    with st.sidebar.expander("Como conectar ao Drive institucional"):
        st.caption("Veja o arquivo SETUP_DRIVE.md incluído junto com este app.")

for key, default in {"last_turma": "", "last_atividade": "", "last_data": date.today()}.items():
    if key not in st.session_state:
        st.session_state[key] = default

# ------------------------------------------------------------------
# Página: Nova Observação
# ------------------------------------------------------------------
if pagina == "📝 Nova Observação":
    st.title("Ficha de Observação Estruturada")
    st.caption("Registro durante os encontros do laboratório — participação, interação, raciocínio científico e autonomia.")

    with st.form("form_observacao", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        data_obs = c1.date_input("Data", value=st.session_state.last_data)
        turma = c2.text_input("Turma", value=st.session_state.last_turma)
        atividade = c3.text_input("Atividade realizada", value=st.session_state.last_atividade)
        grupo_codigo = st.text_input("Grupo/aluno (código) — opcional", placeholder="ex: G3 ou A-014")

        st.markdown("**1. Participação**")
        c1, c2 = st.columns(2)
        participacao_ativa = c1.select_slider("Participação ativa (contribui com ideias e discussões)", ["Baixa", "Média", "Alta"], value="Média")
        engajamento = c2.select_slider("Engajamento (demonstra interesse nas atividades)", ["Baixo", "Médio", "Alto"], value="Médio")

        st.markdown("**2. Interação em grupo**")
        c1, c2 = st.columns(2)
        colaboracao = c1.radio("Colaboração — trabalha em equipe", ["Sim", "Parcial", "Não"], horizontal=True)
        comunicacao_grupo = c2.radio("Comunicação — compartilha ideias com colegas", ["Frequente", "Ocasional", "Rara"], horizontal=True)

        st.markdown("**3. Raciocínio científico**")
        c1, c2, c3 = st.columns(3)
        formula_hipoteses = c1.radio("Formula hipóteses", ["Sim", "Parcial", "Não"])
        controle_variaveis = c2.radio("Controle de variáveis", ["Sim", "Parcial", "Não"])
        interpretacao_resultados = c3.radio("Interpretação de resultados", ["Adequada", "Parcial", "Inadequada"])

        st.markdown("**4. Autonomia**")
        c1, c2 = st.columns(2)
        iniciativa = c1.select_slider("Iniciativa — propõe soluções ou caminhos", ["Baixa", "Média", "Alta"], value="Média")
        tomada_decisao = c2.radio("Tomada de decisão — participa das decisões do grupo", ["Sim", "Parcial", "Não"], horizontal=True)

        observacoes_qualitativas = st.text_area("5. Observações qualitativas (anotações livres)")

        enviado = st.form_submit_button("Salvar observação", use_container_width=True)

        if enviado:
            if not turma or not atividade:
                st.error("Preencha ao menos Turma e Atividade.")
            else:
                insert_observacao({
                    "data": data_obs.isoformat(), "turma": turma, "atividade": atividade,
                    "grupo_codigo": grupo_codigo,
                    "participacao_ativa": participacao_ativa, "engajamento": engajamento,
                    "colaboracao": colaboracao, "comunicacao_grupo": comunicacao_grupo,
                    "formula_hipoteses": formula_hipoteses, "controle_variaveis": controle_variaveis,
                    "interpretacao_resultados": interpretacao_resultados,
                    "iniciativa": iniciativa, "tomada_decisao": tomada_decisao,
                    "observacoes_qualitativas": observacoes_qualitativas,
                    "criado_em": datetime.now().isoformat(),
                })
                st.session_state.last_turma = turma
                st.session_state.last_atividade = atividade
                st.session_state.last_data = data_obs
                if drive_enabled():
                    upload_db_to_drive()
                st.success("Observação salva! Turma/Atividade/Data ficaram pré-preenchidas para o próximo registro.")

# ------------------------------------------------------------------
# Página: Nova Avaliação de Produção
# ------------------------------------------------------------------
elif pagina == "📋 Nova Avaliação de Produção":
    st.title("Rubrica de Avaliação das Produções dos Estudantes")
    st.caption("Um lançamento por aluno/código. Turma, atividade e data ficam salvas para o próximo aluno.")

    c1, c2, c3 = st.columns(3)
    data_av = c1.date_input("Data", value=st.session_state.last_data, key="data_av")
    turma_av = c2.text_input("Turma", value=st.session_state.last_turma, key="turma_av")
    atividade_av = c3.text_input("Atividade", value=st.session_state.last_atividade, key="atividade_av")
    aluno_codigo = st.text_input("Aluno (código)", placeholder="ex: A-014", key="aluno_codigo")

    st.divider()
    valores = {}
    obs = {}
    for criterio in CRITERIOS:
        st.markdown(f"**{criterio}**")
        col_nivel, col_obs = st.columns([1, 2])
        nivel = col_nivel.radio(
            "Nível", [3, 2, 1], format_func=lambda n: NIVEL_LABELS[n],
            key=f"nivel_{criterio}", horizontal=False,
        )
        col_nivel.caption(RUBRICA[criterio][nivel])
        obs[criterio] = col_obs.text_area("Observações", key=f"obs_{criterio}", height=100, label_visibility="collapsed", placeholder="Observações sobre este critério (opcional)")
        valores[criterio] = nivel
        st.write("")

    observacoes_gerais = st.text_area("Observações gerais")

    if st.button("Salvar avaliação", use_container_width=True, type="primary"):
        if not turma_av or not atividade_av or not aluno_codigo:
            st.error("Preencha Turma, Atividade e o código do aluno.")
        else:
            insert_avaliacao({
                "data": data_av.isoformat(), "turma": turma_av, "atividade": atividade_av,
                "aluno_codigo": aluno_codigo,
                "aplicacao_conceitos": valores["Aplicação de conceitos físicos"],
                "obs_aplicacao_conceitos": obs["Aplicação de conceitos físicos"],
                "desenvolvimento_investigativo": valores["Desenvolvimento investigativo"],
                "obs_desenvolvimento_investigativo": obs["Desenvolvimento investigativo"],
                "resolucao_problemas": valores["Resolução de problemas"],
                "obs_resolucao_problemas": obs["Resolução de problemas"],
                "comunicacao_cientifica": valores["Comunicação científica"],
                "obs_comunicacao_cientifica": obs["Comunicação científica"],
                "autonomia": valores["Autonomia"],
                "obs_autonomia": obs["Autonomia"],
                "observacoes_gerais": observacoes_gerais,
                "criado_em": datetime.now().isoformat(),
            })
            st.session_state.last_turma = turma_av
            st.session_state.last_atividade = atividade_av
            st.session_state.last_data = data_av
            if drive_enabled():
                upload_db_to_drive()
            st.success(f"Avaliação de {aluno_codigo} salva! Pronta para o próximo aluno.")
            st.rerun()

# ------------------------------------------------------------------
# Página: Dashboard
# ------------------------------------------------------------------
elif pagina == "📊 Dashboard":
    st.title("Dashboard de Análise")

    df_obs = load_df("observacoes")
    df_av = load_df("avaliacoes")

    if df_obs.empty and df_av.empty:
        st.info("Ainda não há dados lançados. Comece pelas páginas de Nova Observação / Nova Avaliação.")
        st.stop()

    tab_av, tab_obs = st.tabs(["Avaliação de Produções", "Observação Estruturada"])

    # ---- Avaliações ----
    with tab_av:
        if df_av.empty:
            st.info("Nenhuma avaliação lançada ainda.")
        else:
            turmas = sorted(df_av["turma"].dropna().unique())
            c1, c2 = st.columns([1, 2])
            turma_sel = c1.multiselect("Filtrar turma(s)", turmas, default=turmas, key="f_turma_av")
            dmin, dmax = df_av["data"].min(), df_av["data"].max()
            periodo = c2.date_input("Período", value=(dmin, dmax), key="f_periodo_av")

            dff = df_av[df_av["turma"].isin(turma_sel)]
            if isinstance(periodo, tuple) and len(periodo) == 2:
                dff = dff[(dff["data"] >= pd.Timestamp(periodo[0])) & (dff["data"] <= pd.Timestamp(periodo[1]))]

            crit_cols = {
                "Aplicação de conceitos": "aplicacao_conceitos",
                "Desenvolvimento investigativo": "desenvolvimento_investigativo",
                "Resolução de problemas": "resolucao_problemas",
                "Comunicação científica": "comunicacao_cientifica",
                "Autonomia": "autonomia",
            }

            m1, m2, m3 = st.columns(3)
            m1.metric("Avaliações registradas", len(dff))
            m2.metric("Alunos únicos", dff["aluno_codigo"].nunique())
            media_geral = dff[list(crit_cols.values())].mean().mean() if not dff.empty else 0
            m3.metric("Nível médio geral", f"{media_geral:.2f} / 3")

            st.subheader("Nível médio por critério")
            medias = pd.DataFrame({
                "Critério": list(crit_cols.keys()),
                "Nível médio": [dff[c].mean() for c in crit_cols.values()],
            })
            fig_bar = px.bar(medias, x="Nível médio", y="Critério", orientation="h", range_x=[0, 3], text_auto=".2f")
            st.plotly_chart(fig_bar, use_container_width=True)

            st.subheader("Radar por critério")
            fig_radar = go.Figure()
            fig_radar.add_trace(go.Scatterpolar(
                r=medias["Nível médio"], theta=medias["Critério"], fill="toself", name="Média da turma selecionada"
            ))
            fig_radar.update_layout(polar=dict(radialaxis=dict(visible=True, range=[0, 3])), showlegend=False)
            st.plotly_chart(fig_radar, use_container_width=True)

            st.subheader("Evolução semanal (nível médio geral)")
            dff_week = dff.copy()
            dff_week["semana"] = dff_week["data"].dt.to_period("W").apply(lambda p: p.start_time)
            dff_week["media_linha"] = dff_week[list(crit_cols.values())].mean(axis=1)
            evol = dff_week.groupby("semana")["media_linha"].mean().reset_index()
            fig_line = px.line(evol, x="semana", y="media_linha", markers=True, range_y=[0, 3])
            fig_line.update_layout(yaxis_title="Nível médio", xaxis_title="Semana")
            st.plotly_chart(fig_line, use_container_width=True)

            st.subheader("Distribuição de níveis por critério")
            long = dff.melt(id_vars=["aluno_codigo"], value_vars=list(crit_cols.values()), var_name="criterio_col", value_name="nivel")
            inv_map = {v: k for k, v in crit_cols.items()}
            long["Critério"] = long["criterio_col"].map(inv_map)
            long["Nível"] = long["nivel"].map(NIVEL_LABELS)
            fig_dist = px.histogram(long, x="Critério", color="Nível", barmode="stack", category_orders={"Nível": [NIVEL_LABELS[1], NIVEL_LABELS[2], NIVEL_LABELS[3]]})
            st.plotly_chart(fig_dist, use_container_width=True)

            if turma_sel and len(turma_sel) >= 2:
                st.subheader("Comparação entre turmas")
                comp = dff.groupby("turma")[list(crit_cols.values())].mean().reset_index()
                comp_long = comp.melt(id_vars="turma", var_name="criterio_col", value_name="nivel")
                comp_long["Critério"] = comp_long["criterio_col"].map(inv_map)
                fig_comp = px.bar(comp_long, x="Critério", y="nivel", color="turma", barmode="group", range_y=[0, 3])
                st.plotly_chart(fig_comp, use_container_width=True)

    # ---- Observações ----
    with tab_obs:
        if df_obs.empty:
            st.info("Nenhuma observação lançada ainda.")
        else:
            turmas_o = sorted(df_obs["turma"].dropna().unique())
            c1, c2 = st.columns([1, 2])
            turma_sel_o = c1.multiselect("Filtrar turma(s)", turmas_o, default=turmas_o, key="f_turma_obs")
            dmin_o, dmax_o = df_obs["data"].min(), df_obs["data"].max()
            periodo_o = c2.date_input("Período", value=(dmin_o, dmax_o), key="f_periodo_obs")

            dffo = df_obs[df_obs["turma"].isin(turma_sel_o)]
            if isinstance(periodo_o, tuple) and len(periodo_o) == 2:
                dffo = dffo[(dffo["data"] >= pd.Timestamp(periodo_o[0])) & (dffo["data"] <= pd.Timestamp(periodo_o[1]))]

            m1, m2 = st.columns(2)
            m1.metric("Observações registradas", len(dffo))
            m2.metric("Turmas observadas", dffo["turma"].nunique())

            categ_map = {
                "Participação ativa": "participacao_ativa",
                "Engajamento": "engajamento",
                "Colaboração": "colaboracao",
                "Comunicação (grupo)": "comunicacao_grupo",
                "Formula hipóteses": "formula_hipoteses",
                "Controle de variáveis": "controle_variaveis",
                "Interpretação de resultados": "interpretacao_resultados",
                "Iniciativa": "iniciativa",
                "Tomada de decisão": "tomada_decisao",
            }
            escolha = st.selectbox("Ver distribuição de:", list(categ_map.keys()))
            col = categ_map[escolha]
            fig_pie = px.histogram(dffo, x=col, color=col)
            st.plotly_chart(fig_pie, use_container_width=True)

            st.subheader("Observações qualitativas recentes")
            recentes = dffo.sort_values("data", ascending=False)[["data", "turma", "atividade", "observacoes_qualitativas"]].head(10)
            st.dataframe(recentes, use_container_width=True, hide_index=True)

# ------------------------------------------------------------------
# Página: Dados brutos
# ------------------------------------------------------------------
elif pagina == "🗂️ Dados brutos":
    st.title("Dados brutos")
    tabela = st.selectbox("Tabela", ["avaliacoes", "observacoes"])
    df = load_df(tabela)
    st.dataframe(df, use_container_width=True, hide_index=True)

    if not df.empty:
        csv = df.to_csv(index=False).encode("utf-8")
        st.download_button("Baixar CSV", csv, file_name=f"{tabela}.csv", mime="text/csv")

        st.divider()
        st.caption("Excluir um registro (use com cuidado)")
        row_id = st.number_input("ID do registro a excluir", min_value=0, step=1)
        if st.button("Excluir registro"):
            delete_row(tabela, int(row_id))
            if drive_enabled():
                upload_db_to_drive()
            st.success(f"Registro {row_id} excluído.")
            st.rerun()
