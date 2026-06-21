"""
app.py — Aplicação Streamlit para mapas de calor de pesquisa de clima.
"""

import io
import re
import pandas as pd
import numpy as np
import plotly.graph_objects as go
import streamlit as st

# ---------------------------------------------------------------------------
# Feature flags — para desabilitar, trocar True → False
# ---------------------------------------------------------------------------
HABILITAR_ANALISES_APOIO = True

from data_loading import carregar_dados, rotulo_curto, ATRIBUTOS_RECORTE
from metrics import montar_mapa, MIN_RESPONDENTES

# ---------------------------------------------------------------------------
# Configuração da página
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Mapa de Calor — Clima Organizacional",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ---------------------------------------------------------------------------
# Autenticação
# ---------------------------------------------------------------------------
import streamlit_authenticator as stauth

try:
    _auth_creds = dict(st.secrets["credentials"])
    _authenticator = stauth.Authenticate(
        _auth_creds,
        st.secrets["cookie"]["name"],
        st.secrets["cookie"]["key"],
        st.secrets["cookie"]["expiry_days"],
        auto_hash=False,
    )
except KeyError:
    st.error(
        "Configuração de autenticação ausente. "
        "Crie `.streamlit/secrets.toml` a partir do arquivo `.streamlit/secrets.toml.example`."
    )
    st.stop()

_authenticator.login()

if st.session_state.get("authentication_status") is not True:
    if st.session_state.get("authentication_status") is False:
        st.error("Usuário ou senha incorretos.")
    else:
        st.warning("Por favor, faça login para acessar o sistema.")
    st.stop()

_authenticator.logout("Sair", "sidebar")
st.sidebar.caption(f"Logado como: {st.session_state.get('name', '')}")

# ---------------------------------------------------------------------------

st.title("Mapa de Calor — Pesquisa de Clima")

# ===========================================================================
# SIDEBAR — upload + configurações globais
# ===========================================================================
with st.sidebar:
    arquivo = st.file_uploader(
        "Arquivo Excel da pesquisa",
        type=["xlsx", "xls"],
        help="Arquivo com as abas: Anon - Pessoas, Anon - Respostas, eNPS, lNPS, Categorias",
    )

    if arquivo is None:
        st.info("Faça o upload do arquivo Excel para começar.")
        st.stop()

    dados = carregar_dados(arquivo)
    df_pessoas = dados["df_pessoas"]
    atributos_disponiveis = dados["atributos_disponiveis"]
    perguntas = dados["perguntas"]
    nos = dados["nos"]
    caminhos_ordenados = dados["caminhos_ordenados"]

    st.caption(
        f"✓ {len(df_pessoas)} pessoas · {len(perguntas)} perguntas · "
        f"{len(caminhos_ordenados)} áreas"
    )

    with st.expander("⚙️ Configurações"):
        mostrar_avel = st.toggle(
            "Mostrar coluna 'Ável Investimentos'",
            value=True,
            help="Exibe a empresa toda como coluna de referência",
        )
        ocultar_n_baixo = st.toggle(
            f"Ocultar valores com N < {MIN_RESPONDENTES}",
            value=True,
            help=f"Grupos com menos de {MIN_RESPONDENTES} respondentes ficam em branco",
        )
        limiar_faltante = st.slider(
            "Limiar de alerta — dados faltantes (%)",
            min_value=0, max_value=50, value=10, step=5,
            help="Atributos com % de faltantes acima deste valor são destacados.",
        ) / 100

# ---------------------------------------------------------------------------
# Estado de sessão
# ---------------------------------------------------------------------------
if "colunas" not in st.session_state:
    st.session_state.colunas = []

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _df_da_area(caminho: str) -> pd.DataFrame:
    if not caminho:
        return df_pessoas
    cods = nos[caminho].cods if caminho in nos else set()
    return df_pessoas[df_pessoas["cod_ajuste"].isin(cods)]


def _rotulo_de_caminho(caminho: str) -> str:
    if caminho in nos:
        return rotulo_curto(nos[caminho], nos)
    return caminho


def _pct_faltante(df: pd.DataFrame, attr: str) -> float:
    if attr not in df.columns or len(df) == 0:
        return 0.0
    falt = df[attr].isna() | df[attr].astype(str).str.strip().isin(["", "nan", "None"])
    return float(falt.sum()) / len(df)


# ===========================================================================
# CONSTRUTOR DE COLUNAS
# ===========================================================================
st.subheader("Adicionar coluna(s) ao mapa")
st.caption(
    "Escolha uma área e, se quiser, aplique filtros e/ou separe por um atributo. "
    "Deixe **'Não separar'** para uma coluna única, ou escolha um atributo para "
    "comparar grupos lado a lado — ex: Diretoria Comercial separada por Senioridade."
)

_c1, _c2 = st.columns([3, 2])
with _c1:
    caminho_sel = st.selectbox(
        "Área",
        options=[""] + caminhos_ordenados,
        format_func=lambda x: "Ável Investimentos (empresa toda)" if x == "" else x,
        key="sel_area",
    )
with _c2:
    separar_por = st.selectbox(
        "Separar em várias colunas por",
        options=["Não separar"] + list(atributos_disponiveis.keys()),
        key="sel_separar",
    )

with st.expander("Filtros opcionais (recorte)"):
    filtros_sel = {}
    _attrs = list(atributos_disponiveis.keys())
    for _rs in range(0, len(_attrs), 3):
        _fcols = st.columns(3)
        for _fi, _attr in enumerate(_attrs[_rs:_rs + 3]):
            with _fcols[_fi]:
                _sel = st.multiselect(_attr, atributos_disponiveis[_attr], key=f"fs_{_attr}")
                if _sel:
                    filtros_sel[_attr] = _sel

# DF da área sem filtros (para avisos) e com filtros (para valores do "separar por")
df_area_base = _df_da_area(caminho_sel)
df_area_filt = df_area_base.copy()
for _a, _v in filtros_sel.items():
    if _a in df_area_filt.columns:
        df_area_filt = df_area_filt[
            df_area_filt[_a].astype(str).str.strip().isin([str(v).strip() for v in _v])
        ]

# Multiselect de valores e aviso — só quando "separar por" está ativo
vals_sep_disp = []
valores_sep_sel = None

if separar_por != "Não separar":
    if separar_por in df_area_filt.columns:
        vals_sep_disp = sorted(
            v for v in df_area_filt[separar_por].dropna().astype(str).str.strip().unique()
            if v.lower() not in ("nan", "none", "")
        )
    if vals_sep_disp:
        valores_sep_sel = st.multiselect(
            f"Valores de '{separar_por}' a incluir (vazio = todos)",
            vals_sep_disp,
            key="ms_vals_sep",
        )
    _pf_sep = _pct_faltante(df_area_base, separar_por)
    if _pf_sep > limiar_faltante:
        _n_falt_sep = int(_pf_sep * len(df_area_base))
        st.warning(
            f"⚠️ **{_pf_sep:.0%}** das pessoas desta área não têm **{separar_por}** "
            f"preenchido ({_n_falt_sep} pessoa(s)). Elas não aparecem nas colunas separadas "
            f"por esse atributo — os grupos podem não somar o total da área."
        )

for _fa in filtros_sel:
    _pf_f = _pct_faltante(df_area_base, _fa)
    if _pf_f > limiar_faltante:
        _n_falt_f = int(_pf_f * len(df_area_base))
        st.warning(
            f"⚠️ **{_pf_f:.0%}** das pessoas desta área não têm **{_fa}** "
            f"preenchido ({_n_falt_f} pessoa(s)) — elas ficam fora deste filtro."
        )

if st.button("Adicionar ao mapa", type="primary"):
    _caminho_val = caminho_sel if caminho_sel != "" else None
    _nome_base = _rotulo_de_caminho(_caminho_val) if _caminho_val else "Ável Investimentos"

    if separar_por == "Não separar":
        _rotulo = _nome_base
        if filtros_sel:
            _partes = ", ".join(f"{k}: {'/'.join(v)}" for k, v in filtros_sel.items())
            _rotulo = f"{_nome_base} ({_partes})"
        st.session_state.colunas.append({
            "label": _rotulo,
            "area": _caminho_val,
            "filtros": filtros_sel,
        })
    else:
        _vals_usar = valores_sep_sel if valores_sep_sel else vals_sep_disp
        if not _vals_usar:
            st.warning(f"Nenhum valor disponível de '{separar_por}' nesta área/recorte.")
        else:
            for _val in _vals_usar:
                st.session_state.colunas.append({
                    "label": f"{_nome_base} — {_val}",
                    "area": _caminho_val,
                    "filtros": {**filtros_sel, separar_por: [_val]},
                })
    st.rerun()

# Lista de colunas adicionadas
_n_adicionadas = len(st.session_state.colunas)
if _n_adicionadas > 0:
    st.markdown(f"**Colunas adicionadas ({_n_adicionadas})**")
    for _i, _col in enumerate(st.session_state.colunas):
        _ca, _cb = st.columns([9, 1])
        _ca.caption(f"C{_i + 1} — {_col['label']}")
        if _cb.button("✕", key=f"del_{_i}", help="Remover"):
            st.session_state.colunas.pop(_i)
            st.rerun()
    if st.button("Limpar tudo", type="secondary"):
        st.session_state.colunas = []
        st.rerun()

st.divider()

# ===========================================================================
# PAINEL DE QUALIDADE DOS DADOS
# ===========================================================================
_attrs_qual = [a for a in ATRIBUTOS_RECORTE if a in df_pessoas.columns]
_pcts_falt = {a: _pct_faltante(df_pessoas, a) for a in _attrs_qual}
_n_alertas = sum(1 for p in _pcts_falt.values() if p > limiar_faltante)

_label_qual = (
    f"📊 Qualidade dos dados  —  ⚠️ {_n_alertas} atributo(s) acima de {limiar_faltante:.0%} faltante"
    if _n_alertas > 0
    else f"📊 Qualidade dos dados  —  ✓ todos os atributos abaixo de {limiar_faltante:.0%}"
)

with st.expander(_label_qual, expanded=False):
    _total = len(df_pessoas)
    _rows_q = [
        {
            "Atributo": a,
            "Preenchidos": _total - int(_pcts_falt[a] * _total),
            "Faltantes": int(_pcts_falt[a] * _total),
            "% Faltante": _pcts_falt[a],
        }
        for a in _attrs_qual
    ]
    _df_q = pd.DataFrame(_rows_q)

    def _estilo_q(val):
        if isinstance(val, float) and val > limiar_faltante:
            return "background-color: #FFE0B2; color: #BF360C; font-weight: bold"
        return ""

    st.dataframe(
        _df_q.style
            .applymap(_estilo_q, subset=["% Faltante"])
            .format({"% Faltante": "{:.1%}"}),
        use_container_width=True,
        hide_index=True,
    )
    st.caption(
        f"Limiar ajustável em ⚙️ Configurações (barra lateral). "
        f"Células laranja = atributo com mais de {limiar_faltante:.0%} de registros sem preenchimento."
    )

st.divider()

# ===========================================================================
# MONTAR LISTA FINAL E CALCULAR MAPA
# ===========================================================================
colunas_finais = []
if mostrar_avel:
    colunas_finais.append({"label": "Ável Investimentos", "area": None, "filtros": {}})
colunas_finais.extend(st.session_state.colunas)

if not colunas_finais:
    st.info("Adicione colunas na seção acima para gerar o mapa.")
    st.stop()

with st.spinner("Calculando mapa..."):
    df_mapa, df_meta = montar_mapa(colunas_finais, dados)

if df_mapa.empty:
    st.warning("Nenhum dado para exibir.")
    st.stop()

# Máscara N baixo
df_display = df_mapa.copy()
if ocultar_n_baixo:
    _abaixo = df_meta.loc["abaixo_minimo"].astype(bool)
    for _col in df_display.columns:
        if _abaixo.get(_col, False):
            df_display[_col] = np.nan

# Anotações
def formatar_valor(val, linha: str) -> str:
    if pd.isna(val):
        return f"N<{MIN_RESPONDENTES}"
    if linha == "Adesão (%)":
        return f"{val:.2f}%"
    return f"{val:.2f}"


linhas = list(df_display.index)
colunas_labels = list(df_display.columns)
codigos = [f"C{i + 1}" for i in range(len(colunas_labels))]

texto_cells = [
    [formatar_valor(df_display.loc[l, c], l) for c in colunas_labels]
    for l in linhas
]

# Escala dinâmica
METRICAS_FIXAS = ["Engajamento Geral", "ENPS", "LNPS", "Adesão (%)"]

_vals_coloridos = [
    float(df_display.loc[l, c])
    for l in linhas if l not in METRICAS_FIXAS
    for c in colunas_labels
    if pd.notna(df_display.loc[l, c])
]
if _vals_coloridos and (max(_vals_coloridos) - min(_vals_coloridos)) > 0:
    _zmin, _zmax = min(_vals_coloridos), max(_vals_coloridos)
else:
    _zmin, _zmax = 0.0, 100.0

# ===========================================================================
# TABELA DE DADOS BRUTOS — antes do mapa
# ===========================================================================
st.subheader("Tabela de dados")

_df_show = df_display.copy()

def _colorir_tabela(df):
    styles = pd.DataFrame("", index=df.index, columns=df.columns)
    for linha in df.index:
        if linha in METRICAS_FIXAS:
            continue
        for col in df.columns:
            val = df.loc[linha, col]
            if pd.isna(val):
                continue
            norm = float(np.clip((float(val) - _zmin) / (_zmax - _zmin), 0, 1))
            if norm <= 0.5:
                t = norm * 2
                r = int(248 + (255 - 248) * t)
                g = int(105 + (235 - 105) * t)
                b = int(107 + (132 - 107) * t)
            else:
                t = (norm - 0.5) * 2
                r = int(255 + (99 - 255) * t)
                g = int(235 + (190 - 235) * t)
                b = int(132 + (123 - 132) * t)
            styles.loc[linha, col] = f"background-color: rgb({r},{g},{b})"
    return styles

_styled = (
    _df_show.style
    .apply(_colorir_tabela, axis=None)
    .format(lambda v: f"N<{MIN_RESPONDENTES}" if pd.isna(v) else f"{v:.2f}")
)
if "Adesão (%)" in _df_show.index:
    _styled = _styled.format(
        lambda v: f"N<{MIN_RESPONDENTES}" if pd.isna(v) else f"{v:.2f}%",
        subset=pd.IndexSlice["Adesão (%)", :],
    )
st.dataframe(_styled, use_container_width=True)

# ===========================================================================
# LEGENDA COMPACTA — entre a tabela e o mapa
# ===========================================================================
_partes_leg = [
    f"**C{i + 1}** = {col} &nbsp;(N={int(df_meta.loc['respondentes', col])})"
    for i, col in enumerate(colunas_labels)
]
st.caption("  ·  ".join(_partes_leg))

# ===========================================================================
# MAPA DE CALOR
# ===========================================================================
n_linhas = len(linhas)
n_cols = len(colunas_labels)

z_matrix, customdata = [], []
for linha in linhas:
    row_z, row_c = [], []
    sem_cor = linha in METRICAS_FIXAS
    for col in colunas_labels:
        vr = df_display.loc[linha, col]
        if sem_cor:
            vn = None
        elif pd.notna(vr):
            vn = float(np.clip((vr - _zmin) / (_zmax - _zmin) * 100, 0, 100))
        else:
            vn = None
        row_z.append(vn)
        row_c.append((vr, df_meta.loc["respondentes", col], df_meta.loc["participantes", col], col))
    z_matrix.append(row_z)
    customdata.append(row_c)

y_labels_display = [f"<b>{l}</b>" if l in METRICAS_FIXAS else l for l in linhas]
altura = max(500, n_linhas * 36 + 120)

fig = go.Figure(
    go.Heatmap(
        z=z_matrix,
        x=codigos,
        y=y_labels_display,
        text=texto_cells,
        texttemplate="%{text}",
        textfont={"size": 11},
        colorscale="RdYlGn",
        zmin=0,
        zmax=100,
        showscale=True,
        colorbar=dict(
            title="Nota",
            tickvals=[0, 25, 50, 75, 100],
            ticktext=[
                f"{_zmin:.1f}",
                f"{_zmin + 0.25 * (_zmax - _zmin):.1f}",
                f"{_zmin + 0.50 * (_zmax - _zmin):.1f}",
                f"{_zmin + 0.75 * (_zmax - _zmin):.1f}",
                f"{_zmax:.1f}",
            ],
            len=0.8,
        ),
        customdata=customdata,
        hovertemplate=(
            "<b>%{y}</b><br>"
            "Coluna: %{customdata[3]}<br>"
            "Valor: %{customdata[0]:.2f}<br>"
            "Respondentes: %{customdata[1]}<br>"
            "Participantes: %{customdata[2]}"
            "<extra></extra>"
        ),
    )
)

fig.add_shape(
    type="line",
    x0=-0.5, x1=n_cols - 0.5,
    y0=n_linhas - len(METRICAS_FIXAS) - 0.5,
    y1=n_linhas - len(METRICAS_FIXAS) - 0.5,
    line=dict(color="black", width=2, dash="dash"),
)

fig.update_layout(
    height=altura,
    margin=dict(l=200, r=80, t=60, b=120),
    xaxis=dict(side="top", tickangle=-30),
    yaxis=dict(autorange="reversed"),
    title=dict(text="Mapa de Calor — Pesquisa de Clima", font=dict(size=16)),
    plot_bgcolor="white",
)
fig.update_xaxes(
    ticktext=[
        f"C{i + 1}<br><sub>N={int(df_meta.loc['respondentes', col])}</sub>"
        for i, col in enumerate(colunas_labels)
    ],
    tickvals=codigos,
)

st.plotly_chart(fig, use_container_width=True)

if HABILITAR_ANALISES_APOIO:
    from analises_apoio import render_analises_apoio, render_export_ff, ANALISES_ATIVAS as _aa
    render_analises_apoio(df_display, df_meta, colunas_finais, dados)
    _ff_export_ativa = _aa.get("forcas_fraquezas", False)
else:
    _ff_export_ativa = False

# ===========================================================================
# EXPORTAÇÃO
# ===========================================================================
def _nome_arquivo(labels: list[str], ext: str) -> str:
    """Gera nome de arquivo descritivo a partir dos rótulos das colunas."""
    if not labels:
        return f"mapa_de_calor.{ext}"
    if len(labels) == 1:
        base = labels[0]
    elif len(labels) <= 3:
        base = " + ".join(labels)
    else:
        base = f"{labels[0]} +{len(labels) - 1} colunas"
    base = re.sub(r'[<>:"/\\|?*]', "", base)
    base = re.sub(r"\s+", "_", base).strip("_")
    return f"mapa_{base[:100]}.{ext}"


@st.cache_data
def gerar_excel(df_mapa_json: str, df_meta_json: str) -> bytes:
    df_m = pd.read_json(io.StringIO(df_mapa_json))
    df_mt = pd.read_json(io.StringIO(df_meta_json))

    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
        df_m.round(2).to_excel(
            writer, sheet_name="Mapa de Calor", startrow=1, header=False
        )
        workbook = writer.book
        ws = writer.sheets["Mapa de Calor"]

        hdr_fmt = workbook.add_format({
            "text_wrap": True, "bold": True,
            "align": "center", "valign": "vcenter",
            "bg_color": "#D9D9D9", "border": 1,
        })
        ws.set_row(0, 60)
        ws.write(0, 0, "", hdr_fmt)
        for _ci, _cn in enumerate(df_m.columns):
            ws.write(0, _ci + 1, _cn, hdr_fmt)

        _n_dr = len(df_m)
        _n_cx = len(df_m.columns)
        _fixas = {"Engajamento Geral", "ENPS", "LNPS", "Adesão (%)"}
        _n_fx = sum(1 for idx in df_m.index if idx in _fixas)
        _pc = 1 + _n_fx
        if _pc <= _n_dr:
            ws.conditional_format(
                _pc, 1, _n_dr, _n_cx,
                {
                    "type": "3_color_scale",
                    "min_color": "#F8696B",
                    "mid_color": "#FFEB84",
                    "max_color": "#63BE7B",
                },
            )
        ws.set_column(0, 0, 35)
        ws.set_column(1, _n_cx, 28)
        df_mt.to_excel(writer, sheet_name="Meta")
    return output.getvalue()


# ===========================================================================
# EXPORTAÇÕES — barra lateral (renderizado após todo o cálculo)
# ===========================================================================
with st.sidebar:
    st.markdown("---")
    with st.expander("📥 Exportar", expanded=False):
        if df_mapa.empty:
            st.caption("Monte o mapa para exportar.")
        else:
            # ---- Mapa de calor ----
            st.markdown("**Mapa de calor**")
            _sb1, _sb2 = st.columns(2)
            with _sb1:
                try:
                    _lxls = {
                        col: f"{col}  (N={int(df_meta.loc['respondentes', col])})"
                        for col in colunas_labels
                    }
                    st.download_button(
                        "⬇️ Excel",
                        data=gerar_excel(
                            df_mapa.rename(columns=_lxls).to_json(),
                            df_meta.rename(columns=_lxls).to_json(),
                        ),
                        file_name=_nome_arquivo(colunas_labels, "xlsx"),
                        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True,
                        key="_sb_xlsx",
                    )
                except Exception as _e:
                    st.error(f"Erro Excel: {_e}")
            with _sb2:
                try:
                    _sb_leg = [
                        f"C{i + 1} = {col}  (N={int(df_meta.loc['respondentes', col])})"
                        for i, col in enumerate(colunas_labels)
                    ]
                    fig_png = go.Figure(
                        go.Heatmap(
                            z=z_matrix,
                            x=codigos,
                            y=y_labels_display,
                            text=texto_cells,
                            texttemplate="%{text}",
                            textfont={"size": 11},
                            colorscale="RdYlGn",
                            zmin=0,
                            zmax=100,
                            showscale=True,
                            colorbar=dict(
                                title="Nota",
                                tickvals=[0, 25, 50, 75, 100],
                                ticktext=[
                                    f"{_zmin:.1f}",
                                    f"{_zmin + 0.25 * (_zmax - _zmin):.1f}",
                                    f"{_zmin + 0.50 * (_zmax - _zmin):.1f}",
                                    f"{_zmin + 0.75 * (_zmax - _zmin):.1f}",
                                    f"{_zmax:.1f}",
                                ],
                                len=0.8,
                            ),
                        )
                    )
                    fig_png.add_shape(
                        type="line",
                        x0=-0.5, x1=n_cols - 0.5,
                        y0=n_linhas - len(METRICAS_FIXAS) - 0.5,
                        y1=n_linhas - len(METRICAS_FIXAS) - 0.5,
                        line=dict(color="black", width=2, dash="dash"),
                    )
                    fig_png.add_annotation(
                        text="<br>".join(_sb_leg),
                        xref="paper", yref="paper",
                        x=0.0, y=-0.02,
                        xanchor="left", yanchor="top",
                        showarrow=False,
                        font=dict(size=10, family="monospace"),
                        align="left",
                        bgcolor="white",
                        bordercolor="#cccccc",
                        borderwidth=1,
                        borderpad=6,
                    )
                    fig_png.update_layout(
                        width=max(1200, n_cols * 120),
                        height=altura,
                        margin=dict(l=220, r=100, t=120, b=max(80, len(colunas_labels) * 22 + 40)),
                        xaxis=dict(side="top", tickangle=-30),
                        yaxis=dict(autorange="reversed"),
                        title=dict(text="Mapa de Calor — Pesquisa de Clima", font=dict(size=16)),
                        plot_bgcolor="white",
                    )
                    fig_png.update_xaxes(
                        ticktext=[
                            f"C{i + 1}  (N={int(df_meta.loc['respondentes', col])})"
                            for i, col in enumerate(colunas_labels)
                        ],
                        tickvals=codigos,
                    )
                    from concurrent.futures import ThreadPoolExecutor
                    with ThreadPoolExecutor(max_workers=1) as _pool:
                        _img_bytes = _pool.submit(
                            lambda: fig_png.to_image(format="png", scale=2)
                        ).result(timeout=60)
                    st.download_button(
                        "⬇️ PNG",
                        data=_img_bytes,
                        file_name=_nome_arquivo(colunas_labels, "png"),
                        mime="image/png",
                        use_container_width=True,
                        key="_sb_png",
                    )
                except Exception as _e:
                    st.error(f"Erro PNG: {_e}")

            # ---- Forças e Fraquezas ----
            if _ff_export_ativa:
                st.markdown("**Forças e Fraquezas**")
                render_export_ff(df_display, df_meta)

            # ---- Relatório PDF ----
            st.markdown("---")
            st.markdown("**Relatório PDF**")
            _rel_tabela = st.checkbox("Tabela de Dados", value=True, key="_rel_tabela")
            _rel_heatmap = st.checkbox("Mapa de Calor", value=True, key="_rel_heatmap")
            _rel_ff = st.checkbox(
                "Forças e Fraquezas",
                value=bool(_ff_export_ativa),
                disabled=not _ff_export_ativa,
                key="_rel_ff",
            )
            _rel_insat = st.checkbox("% de Insatisfeitos", value=False, key="_rel_insat")
            _rel_rank = st.checkbox("Ranking por categoria", value=False, key="_rel_rank")
            _rel_qual = st.checkbox("Qualidade dos dados", value=False, key="_rel_qual")

            _secoes_sel = (
                (["tabela"] if _rel_tabela else [])
                + (["heatmap"] if _rel_heatmap else [])
                + (["forcas_fraquezas"] if _rel_ff else [])
                + (["insatisfeitos"] if _rel_insat else [])
                + (["ranking"] if _rel_rank else [])
                + (["qualidade"] if _rel_qual else [])
            )

            if st.button(
                "🔄 Gerar relatório",
                key="_sb_gerar_rel",
                use_container_width=True,
                disabled=not _secoes_sel,
            ):
                from relatorio import gerar_relatorio_pdf
                _ctx_rel = {
                    "df_display": df_display,
                    "df_meta": df_meta,
                    "colunas_labels": colunas_labels,
                    "colunas_finais": colunas_finais,
                    "dados": dados,
                    "fig_plotly": fig,
                    "cat_ranking": st.session_state.get("_a3_cat"),
                    "limiar_faltante": limiar_faltante,
                    "atributos_recorte": list(atributos_disponiveis.keys()),
                }
                with st.spinner("Gerando relatório…"):
                    st.session_state["_relatorio_bytes"] = gerar_relatorio_pdf(
                        _secoes_sel, _ctx_rel
                    )

            if st.session_state.get("_relatorio_bytes"):
                st.download_button(
                    "⬇️ Baixar relatório (PDF)",
                    data=st.session_state["_relatorio_bytes"],
                    file_name=_nome_arquivo(colunas_labels, "pdf"),
                    mime="application/pdf",
                    use_container_width=True,
                    key="_sb_baixar_rel",
                )
