"""
analises_apoio.py — Análises complementares ao mapa de calor de clima organizacional.
"""

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from metrics import filtrar_pessoas, MIN_RESPONDENTES

import io
import math
import textwrap

try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as _plt
    import matplotlib.patches as _mpl_patches
    from matplotlib.backends.backend_pdf import PdfPages as _PdfPages
    _MPL_OK = True
except Exception:
    _MPL_OK = False

_METRICAS_FIXAS = {"Engajamento Geral", "ENPS", "LNPS", "Adesão (%)"}
_LIMIAR_INSATISFEITO = 25

ANALISES_ATIVAS = {
    "gaps_vs_referencia": False,    # Análise 1 — desligada (pode confundir o RH)
    "modo_diferenca": False,        # Análise 2 — desligada
    "ranking_por_categoria": True,  # Análise 3
    "forcas_fraquezas": True,       # Análise 4
    "insatisfeitos": True,          # Análise 5
}


def _ref_col(df):
    if "Ável Investimentos" in df.columns:
        return "Ável Investimentos"
    return df.columns[0]


def _cats(df):
    return [l for l in df.index if l not in _METRICAS_FIXAS]


def _rdylgn(norm):
    norm = float(np.clip(norm, 0.0, 1.0))
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
    return f"rgb({r},{g},{b})"


def _analise_1(df_display, df_meta):
    with st.expander("1 · Gaps vs. referência", expanded=False):
        st.caption(
            "Compara cada coluna do mapa com a referência (Ável Investimentos) e lista as "
            "categorias com maior afastamento, positivo ou negativo."
        )
        limiar = st.slider("Limiar mínimo de gap", 0, 30, 10, key="_a1_limiar")
        top_n = st.slider("Máximo de itens por coluna", 1, 20, 5, key="_a1_topn")

        ref = _ref_col(df_display)
        cats = _cats(df_display)

        if not cats:
            st.info("Nenhuma categoria disponível.")
            return

        outras_colunas = [c for c in df_display.columns if c != ref]
        if not outras_colunas:
            st.info("Apenas uma coluna no mapa — adicione mais colunas para comparar gaps.")
            return

        for i, col in enumerate(outras_colunas):
            n_resp = int(df_meta.loc["respondentes", col]) if col in df_meta.columns else 0
            st.markdown(f"**C{i + 2} — {col}** (N={n_resp})")

            rows = []
            for cat in cats:
                nota = df_display.loc[cat, col] if cat in df_display.index else np.nan
                nota_ref = df_display.loc[cat, ref] if cat in df_display.index else np.nan
                if pd.isna(nota) or pd.isna(nota_ref):
                    continue
                delta = float(nota) - float(nota_ref)
                if abs(delta) >= limiar:
                    rows.append({"Categoria": cat, "Nota": float(nota), "Δ": delta})

            if not rows:
                st.caption("Nenhum gap acima do limiar.")
                st.markdown("---")
                continue

            df_gaps = pd.DataFrame(rows)
            negativos = df_gaps[df_gaps["Δ"] < 0].sort_values("Δ").head(top_n)
            positivos = df_gaps[df_gaps["Δ"] > 0].sort_values("Δ", ascending=False).head(top_n)

            col_neg, col_pos = st.columns(2)
            with col_neg:
                st.markdown("🔴 **Pontos de atenção**")
                if negativos.empty:
                    st.caption("Nenhum.")
                else:
                    st.dataframe(
                        negativos.style.format({"Nota": "{:.2f}", "Δ": "{:+.2f}"}),
                        use_container_width=True,
                        hide_index=True,
                    )
            with col_pos:
                st.markdown("🟢 **Destaques positivos**")
                if positivos.empty:
                    st.caption("Nenhum.")
                else:
                    st.dataframe(
                        positivos.style.format({"Nota": "{:.2f}", "Δ": "{:+.2f}"}),
                        use_container_width=True,
                        hide_index=True,
                    )
            st.markdown("---")


def _analise_2(df_display, df_meta):
    with st.expander("2 · Mapa Δ", expanded=False):
        st.caption(
            "Exibe nota − referência em vez da nota absoluta. "
            "Verde = acima da referência · Vermelho = abaixo · Branco ≈ igual."
        )

        ref = _ref_col(df_display)
        cats = _cats(df_display)
        outras = [c for c in df_display.columns if c != ref]

        if not cats or not outras:
            st.info("São necessárias pelo menos duas colunas e uma categoria para exibir o Mapa Δ.")
            return

        delta_data = {}
        for col in outras:
            deltas = []
            for cat in cats:
                nota = df_display.loc[cat, col] if cat in df_display.index else np.nan
                nota_ref = df_display.loc[cat, ref] if cat in df_display.index else np.nan
                if pd.isna(nota) or pd.isna(nota_ref):
                    deltas.append(np.nan)
                else:
                    deltas.append(float(nota) - float(nota_ref))
            delta_data[col] = deltas

        df_delta = pd.DataFrame(delta_data, index=cats)

        all_vals = df_delta.values.flatten()
        all_vals = all_vals[~np.isnan(all_vals)]
        max_abs = max(float(np.max(np.abs(all_vals))) if len(all_vals) > 0 else 10, 10)

        codigos = [f"C{list(df_display.columns).index(c) + 1}" for c in outras]
        ticktext = [
            f"C{list(df_display.columns).index(c) + 1}<br><sub>N={int(df_meta.loc['respondentes', c])}</sub>"
            for c in outras
        ]

        fig = go.Figure(
            go.Heatmap(
                z=df_delta.values.tolist(),
                x=codigos,
                y=list(df_delta.index),
                colorscale="RdYlGn",
                zmid=0,
                zmin=-max_abs,
                zmax=max_abs,
                text=[[f"{v:+.2f}" if not np.isnan(v) else "N/D" for v in row] for row in df_delta.values],
                texttemplate="%{text}",
                textfont={"size": 11},
                showscale=True,
            )
        )
        fig.update_layout(
            height=max(400, len(cats) * 36 + 120),
            margin=dict(l=200, r=80, t=60, b=100),
            xaxis=dict(side="top", tickangle=-30, ticktext=ticktext, tickvals=codigos),
            yaxis=dict(autorange="reversed"),
            title=dict(text=f"Δ vs. {ref}", font=dict(size=14)),
            plot_bgcolor="white",
        )
        st.plotly_chart(fig, use_container_width=True)

        legenda = "  ·  ".join(
            f"**C{list(df_display.columns).index(c) + 1}** = {c}" for c in outras
        )
        st.caption(legenda)


def _analise_3(df_display, df_meta):
    with st.expander("3 · Ranking por categoria", expanded=False):
        st.caption(
            "Escolha uma categoria ou métrica e veja as colunas do mapa ordenadas "
            "da maior para a menor nota."
        )

        todas_linhas = list(df_display.index)
        if not todas_linhas:
            st.info("Nenhuma linha disponível.")
            return

        _a3_default = (
            todas_linhas.index("Engajamento Geral")
            if "Engajamento Geral" in todas_linhas else 0
        )
        cat_sel = st.selectbox(
            "Categoria / Métrica", todas_linhas, index=_a3_default, key="_a3_cat"
        )

        row = df_display.loc[cat_sel]
        row_validos = row.dropna().sort_values(ascending=False)

        if row_validos.empty:
            st.info("Nenhum dado disponível para esta categoria.")
            return

        all_notas = df_display.loc[_cats(df_display)].values.flatten()
        all_notas = all_notas[~pd.isna(all_notas)].astype(float)
        nota_min = float(np.min(all_notas)) if len(all_notas) > 0 else 0.0
        nota_max = float(np.max(all_notas)) if len(all_notas) > 0 else 100.0
        rng = nota_max - nota_min if nota_max != nota_min else 1.0

        bar_colors = [
            _rdylgn((float(v) - nota_min) / rng) for v in row_validos.values
        ]

        fig = go.Figure(
            go.Bar(
                x=list(row_validos.index),
                y=list(row_validos.values),
                marker_color=bar_colors,
                text=[f"{v:.2f}" for v in row_validos.values],
                textposition="outside",
            )
        )
        fig.update_layout(
            height=400,
            margin=dict(l=60, r=60, t=60, b=120),
            xaxis=dict(tickangle=-30),
            yaxis=dict(title="Nota"),
            title=dict(text=f"Ranking — {cat_sel}", font=dict(size=14)),
            plot_bgcolor="white",
        )
        st.plotly_chart(fig, use_container_width=True)

        ranking_rows = []
        for pos, (col, nota) in enumerate(row_validos.items(), start=1):
            n_resp = int(df_meta.loc["respondentes", col]) if col in df_meta.columns else 0
            ranking_rows.append({"Posição": pos, "Coluna": col, "Nota": round(float(nota), 2), "N respondentes": n_resp})

        st.dataframe(
            pd.DataFrame(ranking_rows).style.format({"Nota": "{:.2f}"}),
            use_container_width=True,
            hide_index=True,
        )


# ---------------------------------------------------------------------------
# Análise 4 — helpers de cálculo e exportação
# ---------------------------------------------------------------------------

_FF_RED_BG  = "#FFEBEE"
_FF_RED_TXT = "#C62828"
_FF_GRN_BG  = "#E8F5E9"
_FF_GRN_TXT = "#2E7D32"
_FF_BORDER  = "#CCCCCC"
_FF_DIV     = "#DDDDDD"


def _calcular_ff(df_display, df_meta):
    """Extrai forças/fraquezas de cada coluna sem renderizar."""
    cats = _cats(df_display)
    result = []
    for i, col in enumerate(df_display.columns):
        n_resp = int(df_meta.loc["respondentes", col]) if col in df_meta.columns else 0
        col_data = df_display.loc[cats, col].dropna().sort_values()
        if col_data.empty:
            continue
        result.append({
            "idx": i + 1,
            "label": col,
            "n": n_resp,
            "fraquezas": [(c, float(v)) for c, v in col_data.head(3).items()],
            "forcas": [(c, float(v)) for c, v in col_data.tail(3).sort_values(ascending=False).items()],
        })
    return result


def _draw_ff_block(ax, bloco):
    """Desenha o bloco de uma coluna num axes matplotlib."""
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")

    ax.add_patch(_mpl_patches.Rectangle(
        (0.01, 0.01), 0.98, 0.98,
        linewidth=1.0, edgecolor=_FF_BORDER, facecolor="white"
    ))

    short = bloco["label"][:37] + ("…" if len(bloco["label"]) > 37 else "")
    ax.text(0.5, 0.93, f"C{bloco['idx']} — {short}",
            ha="center", va="top", fontsize=8.5, fontweight="bold", color="#1A1A1A")
    ax.text(0.5, 0.86, f"N = {bloco['n']}",
            ha="center", va="top", fontsize=8, color="#555555")

    ax.plot([0.04, 0.96], [0.81, 0.81], color=_FF_DIV, lw=0.8)
    ax.text(0.25, 0.78, "Fraquezas", ha="center", va="top",
            fontsize=8.5, fontweight="bold", color=_FF_RED_TXT)
    ax.text(0.75, 0.78, "Forças", ha="center", va="top",
            fontsize=8.5, fontweight="bold", color=_FF_GRN_TXT)
    ax.plot([0.50, 0.50], [0.74, 0.03], color=_FF_DIV, lw=0.6)

    for j, y_top in enumerate([0.73, 0.49, 0.25]):
        y_bot = y_top - 0.22
        y_mid = (y_top + y_bot) / 2

        if j < len(bloco["fraquezas"]):
            cat, nota = bloco["fraquezas"][j]
            ax.add_patch(_mpl_patches.Rectangle(
                (0.02, y_bot + 0.01), 0.46, 0.20,
                linewidth=0, facecolor=_FF_RED_BG, zorder=1))
            ax.text(0.04, y_top - 0.02,
                    "\n".join(textwrap.wrap(cat, width=22)),
                    ha="left", va="top", fontsize=6.5, color="#333333",
                    linespacing=1.2, zorder=2)
            ax.text(0.46, y_mid, f"{nota:.1f}",
                    ha="right", va="center", fontsize=10,
                    fontweight="bold", color=_FF_RED_TXT, zorder=2)

        if j < len(bloco["forcas"]):
            cat, nota = bloco["forcas"][j]
            ax.add_patch(_mpl_patches.Rectangle(
                (0.52, y_bot + 0.01), 0.46, 0.20,
                linewidth=0, facecolor=_FF_GRN_BG, zorder=1))
            ax.text(0.54, y_top - 0.02,
                    "\n".join(textwrap.wrap(cat, width=22)),
                    ha="left", va="top", fontsize=6.5, color="#333333",
                    linespacing=1.2, zorder=2)
            ax.text(0.96, y_mid, f"{nota:.1f}",
                    ha="right", va="center", fontsize=10,
                    fontweight="bold", color=_FF_GRN_TXT, zorder=2)


def _figura_ff(blocos, n_cols):
    n = len(blocos)
    n_rows = math.ceil(n / n_cols)
    fig, axes = _plt.subplots(
        n_rows, n_cols,
        figsize=(n_cols * 4.5, n_rows * 4.2 + 0.5),
        squeeze=False,
    )
    for i, bloco in enumerate(blocos):
        _draw_ff_block(axes[i // n_cols][i % n_cols], bloco)
    for i in range(n, n_rows * n_cols):
        axes[i // n_cols][i % n_cols].set_visible(False)
    return fig


def _bytes_png_ff(blocos):
    n_cols = min(3, len(blocos))
    fig = _figura_ff(blocos, n_cols)
    fig.suptitle("Forças e Fraquezas — Pesquisa de Clima",
                 fontsize=13, fontweight="bold", y=0.99)
    fig.tight_layout(rect=[0, 0, 1, 0.96])
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=200, bbox_inches="tight")
    _plt.close(fig)
    return buf.getvalue()


def _bytes_pdf_ff(blocos):
    n_cols = min(3, len(blocos))
    per_page = n_cols * 2
    paginas = [blocos[i:i + per_page] for i in range(0, len(blocos), per_page)]
    buf = io.BytesIO()
    with _PdfPages(buf) as pdf:
        for p_i, pag in enumerate(paginas):
            fig = _figura_ff(pag, n_cols)
            titulo = "Forças e Fraquezas — Pesquisa de Clima"
            if len(paginas) > 1:
                titulo += f"  ({p_i + 1}/{len(paginas)})"
            fig.suptitle(titulo, fontsize=13, fontweight="bold", y=0.99)
            fig.tight_layout(rect=[0, 0, 1, 0.96])
            pdf.savefig(fig, bbox_inches="tight")
            _plt.close(fig)
    return buf.getvalue()


# ---------------------------------------------------------------------------
# Análise 4 — renderização
# ---------------------------------------------------------------------------

def _analise_4(df_display, df_meta):
    with st.expander("4 · Forças e fraquezas", expanded=False):
        st.caption(
            "Para cada coluna, as 3 categorias com maior e menor nota "
            "(comparação interna, independente da referência)."
        )

        blocos = _calcular_ff(df_display, df_meta)

        if not blocos:
            st.info("Nenhuma categoria disponível.")
            return

        for bloco in blocos:
            st.markdown(f"**C{bloco['idx']} — {bloco['label']}** (N={bloco['n']})")
            c_neg, c_pos = st.columns(2)
            with c_neg:
                st.markdown("🔴 **Menores notas**")
                st.dataframe(
                    pd.DataFrame([{"Categoria": c, "Nota": round(v, 2)}
                                  for c, v in bloco["fraquezas"]])
                    .style.format({"Nota": "{:.2f}"}),
                    use_container_width=True, hide_index=True,
                )
            with c_pos:
                st.markdown("🟢 **Maiores notas**")
                st.dataframe(
                    pd.DataFrame([{"Categoria": c, "Nota": round(v, 2)}
                                  for c, v in bloco["forcas"]])
                    .style.format({"Nota": "{:.2f}"}),
                    use_container_width=True, hide_index=True,
                )
            st.markdown("---")


def _analise_5(df_display, df_meta, colunas_finais, dados):
    with st.expander("5 · % de Insatisfeitos", expanded=False):
        st.caption(
            "Percentual de respondentes que deram notas baixas em cada categoria. "
            f"**Insatisfeito (Likert)** = resposta ≤ {_LIMIAR_INSATISFEITO}."
        )

        df_pessoas = dados["df_pessoas"]
        df_respostas = dados["df_respostas"]
        perguntas = dados["perguntas"]
        nos = dados.get("nos")

        status_col = next(
            (c for c in df_respostas.columns if c.strip().lower() == "status"), None
        )
        if status_col:
            df_resp_fin = df_respostas[
                df_respostas[status_col].astype(str).str.strip().str.upper() == "FINISHED"
            ]
        else:
            df_resp_fin = df_respostas

        cats = _cats(df_display)
        pergs_por_cat = {
            cat: [p for p in perguntas if p.categoria == cat and p.tipo != "nps"]
            for cat in cats
        }

        resultado_rows = []

        for cfg, col_label in zip(colunas_finais, df_display.columns):
            cods = filtrar_pessoas(
                df_pessoas,
                cfg.get("area"),
                cfg.get("filtros", {}),
                nos=nos,
            )
            df_col = df_resp_fin[df_resp_fin["cod_ajuste"].isin(cods)]

            for cat in cats:
                pergs_cat = pergs_por_cat.get(cat, [])
                if not pergs_cat:
                    continue

                valores = []
                for p in pergs_cat:
                    if p.col_resp not in df_col.columns:
                        continue
                    vals = pd.to_numeric(df_col[p.col_resp], errors="coerce").dropna().tolist()
                    valores.extend(vals)

                if len(valores) < MIN_RESPONDENTES:
                    continue

                arr = np.array(valores, dtype=float)
                pct_insatisfeito = float(np.mean(arr <= _LIMIAR_INSATISFEITO) * 100)
                nota_media = df_display.loc[cat, col_label]

                resultado_rows.append({
                    "Coluna": col_label,
                    "Categoria": cat,
                    "Nota média": round(float(nota_media), 2) if pd.notna(nota_media) else None,
                    "% insatisfeitos": round(pct_insatisfeito, 1),
                })

        if not resultado_rows:
            st.info("Sem dados suficientes para calcular o % de insatisfeitos.")
            return

        st.dataframe(
            pd.DataFrame(resultado_rows)
            .style.format({
                "Nota média": "{:.2f}",
                "% insatisfeitos": "{:.1f}%",
            }, na_rep="—"),
            use_container_width=True,
            hide_index=True,
        )
        st.caption(f"Insatisfeito = resposta Likert ≤ {_LIMIAR_INSATISFEITO}.")


def render_export_ff(df_display, df_meta):
    """Botões de exportação de Forças e Fraquezas para uso na barra lateral."""
    if not _MPL_OK:
        st.caption("Instale `matplotlib` para exportar.")
        return
    blocos = _calcular_ff(df_display, df_meta)
    if not blocos:
        st.caption("Sem dados para exportar.")
        return
    _c1, _c2 = st.columns(2)
    with _c1:
        st.download_button(
            "⬇️ PNG",
            data=_bytes_png_ff(blocos),
            file_name="forcas_fraquezas.png",
            mime="image/png",
            use_container_width=True,
            key="_sb_ff_png",
        )
    with _c2:
        st.download_button(
            "⬇️ PDF",
            data=_bytes_pdf_ff(blocos),
            file_name="forcas_fraquezas.pdf",
            mime="application/pdf",
            use_container_width=True,
            key="_sb_ff_pdf",
        )


def render_analises_apoio(df_display, df_meta, colunas_finais, dados):
    if df_display.empty:
        st.info("Monte o mapa de calor acima para habilitar as análises.")
        return

    with st.expander("📊 Análises de apoio à decisão", expanded=False):
        if ANALISES_ATIVAS["gaps_vs_referencia"]:
            _analise_1(df_display, df_meta)
        if ANALISES_ATIVAS["modo_diferenca"]:
            _analise_2(df_display, df_meta)
        if ANALISES_ATIVAS["ranking_por_categoria"]:
            _analise_3(df_display, df_meta)
        if ANALISES_ATIVAS["forcas_fraquezas"]:
            _analise_4(df_display, df_meta)
        if ANALISES_ATIVAS["insatisfeitos"]:
            _analise_5(df_display, df_meta, colunas_finais, dados)
