"""
relatorio.py — Montagem de relatório PDF multi-seções.

Cada seção é independente; adicionar ou remover é trivial.
Importar via: from relatorio import gerar_relatorio_pdf
"""

import io
import math
from concurrent.futures import ThreadPoolExecutor
from datetime import date

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as _mp
from matplotlib.backends.backend_pdf import PdfPages
from matplotlib.colors import LinearSegmentedColormap
import numpy as np
import pandas as pd

from analises_apoio import _calcular_ff, _figura_ff
from metrics import filtrar_pessoas, MIN_RESPONDENTES

# ---------------------------------------------------------------------------
# Constantes
# ---------------------------------------------------------------------------
_METRICAS_FIXAS = {"Engajamento Geral", "ENPS", "LNPS", "Adesão (%)"}
_LIMIAR_INSATISFEITO = 25

SECOES_LABELS = {
    "tabela":           "Tabela de Dados",
    "heatmap":          "Mapa de Calor",
    "forcas_fraquezas": "Forças e Fraquezas",
    "insatisfeitos":    "% de Insatisfeitos",
    "ranking":          "Ranking por Categoria",
    "qualidade":        "Qualidade dos Dados",
}

_RDYLGN = LinearSegmentedColormap.from_list("rdylgn_app", [
    (248/255, 105/255, 107/255),
    (255/255, 235/255, 132/255),
    (99/255,  190/255, 123/255),
])


def _rgn(norm):
    """RdYlGn como tupla (r,g,b) em [0,1]."""
    norm = max(0.0, min(1.0, float(norm)))
    if norm <= 0.5:
        t = norm * 2
        return ((248+(255-248)*t)/255, (105+(235-105)*t)/255, (107+(132-107)*t)/255)
    t = (norm-0.5)*2
    return ((255+(99-255)*t)/255, (235+(190-235)*t)/255, (132+(123-132)*t)/255)


# ---------------------------------------------------------------------------
# Capa
# ---------------------------------------------------------------------------
def _capa(pdf, secoes, ctx):
    colunas_labels = ctx["colunas_labels"]
    df_meta = ctx["df_meta"]

    fig, ax = plt.subplots(figsize=(11, 8.5))
    ax.set_xlim(0, 1); ax.set_ylim(0, 1); ax.axis("off")

    ax.add_patch(_mp.Rectangle((0, 0.88), 1, 0.12, facecolor="#2C3E50",
                                transform=ax.transAxes, zorder=1))
    ax.text(0.5, 0.94, "Relatório — Pesquisa de Clima",
            ha="center", va="center", fontsize=18, fontweight="bold", color="white", zorder=2)
    ax.text(0.97, 0.84, date.today().strftime("%d/%m/%Y"),
            ha="right", va="top", fontsize=10, color="#555555")

    ax.text(0.04, 0.80, "Colunas do mapa:",
            fontsize=11, fontweight="bold", color="#1A1A1A", va="top")
    for i, col in enumerate(colunas_labels[:15]):
        n = int(df_meta.loc["respondentes", col]) if col in df_meta.columns else 0
        short = col if len(col) <= 65 else col[:62] + "…"
        ax.text(0.06, 0.75 - i*0.055, f"C{i+1} = {short}  (N={n})",
                fontsize=8.5, color="#333333", va="top", family="monospace")
    if len(colunas_labels) > 15:
        ax.text(0.06, 0.75 - 15*0.055, f"… e mais {len(colunas_labels)-15} colunas",
                fontsize=8.5, color="#888888", va="top")

    y0 = 0.75 - min(len(colunas_labels), 16)*0.055 - 0.04
    ax.text(0.04, y0, "Seções incluídas:",
            fontsize=11, fontweight="bold", color="#1A1A1A", va="top")
    for j, sec in enumerate(secoes):
        ax.text(0.06, y0 - 0.04 - j*0.046,
                f"• {SECOES_LABELS.get(sec, sec)}", fontsize=9, color="#333333", va="top")

    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Seção 1: Tabela de dados
# ---------------------------------------------------------------------------
def _sec_tabela(pdf, ctx):
    df = ctx["df_display"]
    colunas_labels = ctx["colunas_labels"]

    cats = [r for r in df.index if r not in _METRICAS_FIXAS]
    cat_vals = df.loc[cats].values.flatten() if cats else np.array([])
    cat_vals = cat_vals[~pd.isna(cat_vals)].astype(float)
    zmin = float(cat_vals.min()) if len(cat_vals) > 0 else 0.0
    zmax = float(cat_vals.max()) if len(cat_vals) > 0 else 100.0

    all_rows = list(df.index)
    all_cols = list(df.columns)
    MAX_COLS = 7
    MAX_ROWS = 22
    col_chunks = [all_cols[i:i+MAX_COLS] for i in range(0, len(all_cols), MAX_COLS)]
    row_chunks = [all_rows[i:i+MAX_ROWS] for i in range(0, len(all_rows), MAX_ROWS)]

    for ri, row_ch in enumerate(row_chunks):
        for ci, col_ch in enumerate(col_chunks):
            df_slice = df.loc[row_ch, col_ch]
            n_r, n_c = df_slice.shape

            cell_text, cell_colors = [], []
            for row_name in row_ch:
                rt, rc = [], []
                for col in col_ch:
                    v = df_slice.loc[row_name, col]
                    if pd.isna(v):
                        rt.append("—"); rc.append((0.96, 0.96, 0.96))
                    else:
                        rt.append(f"{v:.1f}")
                        if row_name in _METRICAS_FIXAS:
                            rc.append((1.0, 1.0, 1.0))
                        else:
                            norm = (float(v)-zmin)/(zmax-zmin) if zmax > zmin else 0.5
                            rc.append(_rgn(norm))
                cell_text.append(rt); cell_colors.append(rc)

            col_codes = [f"C{all_cols.index(c)+1}" for c in col_ch]
            row_colors_lbl = [
                (0.86, 0.86, 0.86) if r in _METRICAS_FIXAS else (0.94, 0.94, 0.94)
                for r in row_ch
            ]

            fig_h = max(7.0, n_r * 0.58 + 1.8)
            fig_w = max(10.0, n_c * 2.2 + 3.5)
            fig, ax = plt.subplots(figsize=(fig_w, fig_h))
            ax.axis("off")

            tbl = ax.table(
                cellText=cell_text, rowLabels=row_ch, colLabels=col_codes,
                cellColours=cell_colors, rowColours=row_colors_lbl,
                loc="center", cellLoc="center",
            )
            tbl.auto_set_font_size(False); tbl.set_fontsize(8); tbl.scale(1, 2.2)

            for j in range(n_c):
                tbl[(0, j)].set_facecolor((0.84, 0.84, 0.84))
                tbl[(0, j)].get_text().set_fontweight("bold")

            n_total_r = len(row_chunks); n_total_c = len(col_chunks)
            suffix = (
                f" (linhas {ri+1}/{n_total_r}, colunas {ci+1}/{n_total_c})"
                if n_total_r > 1 or n_total_c > 1 else ""
            )
            ax.set_title(f"Tabela de Dados{suffix}", fontsize=13, fontweight="bold", pad=20)
            pdf.savefig(fig, bbox_inches="tight")
            plt.close(fig)


# ---------------------------------------------------------------------------
# Seção 2: Mapa de calor
# ---------------------------------------------------------------------------
def _sec_heatmap(pdf, ctx):
    fig_plotly = ctx.get("fig_plotly")
    png_bytes = None

    if fig_plotly is not None:
        try:
            _ref = fig_plotly
            with ThreadPoolExecutor(max_workers=1) as pool:
                png_bytes = pool.submit(
                    lambda: _ref.to_image(format="png", scale=2)
                ).result(timeout=60)
        except Exception:
            png_bytes = None

    if png_bytes is not None:
        img_arr = plt.imread(io.BytesIO(png_bytes))
        h, w = img_arr.shape[:2]
        fig_w = min(16.0, w / 130)
        fig_h = min(12.0, h / 130)
        fig, ax = plt.subplots(figsize=(max(10, fig_w), max(7, fig_h)))
        ax.imshow(img_arr); ax.axis("off")
        ax.set_title("Mapa de Calor", fontsize=13, fontweight="bold", pad=10)
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)
    else:
        _sec_heatmap_mpl(pdf, ctx)


def _sec_heatmap_mpl(pdf, ctx):
    """Fallback matplotlib para quando kaleido não disponível."""
    df = ctx["df_display"]
    df_meta = ctx["df_meta"]
    colunas_labels = ctx["colunas_labels"]

    all_rows = list(df.index)
    n_r = len(all_rows); n_c = len(colunas_labels)

    cats = [r for r in all_rows if r not in _METRICAS_FIXAS]
    cat_vals = df.loc[cats].values.flatten() if cats else np.array([])
    cat_vals = cat_vals[~pd.isna(cat_vals)].astype(float)
    zmin = float(cat_vals.min()) if len(cat_vals) > 0 else 0.0
    zmax = float(cat_vals.max()) if len(cat_vals) > 0 else 100.0

    z = np.full((n_r, n_c), np.nan)
    text_mat = [[f"N<{MIN_RESPONDENTES}"] * n_c for _ in range(n_r)]
    for i, row_name in enumerate(all_rows):
        for j, col in enumerate(df.columns):
            v = df.loc[row_name, col]
            if pd.notna(v):
                z[i, j] = float(v)
                text_mat[i][j] = f"{float(v):.1f}"

    z_color = z.copy()
    for i, row_name in enumerate(all_rows):
        if row_name in _METRICAS_FIXAS:
            z_color[i, :] = np.nan

    fig_w = max(12.0, n_c * 1.8 + 3)
    fig_h = max(8.0, n_r * 0.7 + 2.5)
    fig, ax = plt.subplots(figsize=(fig_w, fig_h))

    im = ax.imshow(z_color, cmap=_RDYLGN, vmin=zmin, vmax=zmax, aspect="auto")

    for i, row_name in enumerate(all_rows):
        if row_name in _METRICAS_FIXAS:
            ax.add_patch(plt.Rectangle((-0.5, i-0.5), n_c, 1,
                                        facecolor="#F0F0F0", edgecolor="none", zorder=0))

    for i in range(n_r):
        for j in range(n_c):
            ax.text(j, i, text_mat[i][j], ha="center", va="center",
                    fontsize=7.5, color="black", zorder=2)

    codigos = [f"C{j+1}" for j in range(n_c)]
    ax.set_xticks(range(n_c)); ax.set_xticklabels(codigos, fontsize=9)
    ax.xaxis.set_ticks_position("top"); ax.xaxis.set_label_position("top")
    ax.tick_params(top=True, bottom=False)
    ax.set_yticks(range(n_r)); ax.set_yticklabels(all_rows, fontsize=8)

    n_fixas = sum(1 for r in all_rows if r in _METRICAS_FIXAS)
    if 0 < n_fixas < n_r:
        ax.axhline(y=n_fixas-0.5, color="black", lw=1.5, ls="--", zorder=3)

    plt.colorbar(im, ax=ax, shrink=0.7, label="Nota")
    ax.set_title("Mapa de Calor", fontsize=13, fontweight="bold", pad=40)
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Seção 3: Forças e Fraquezas
# ---------------------------------------------------------------------------
def _sec_ff(pdf, ctx):
    blocos = _calcular_ff(ctx["df_display"], ctx["df_meta"])
    if not blocos:
        return
    n_cols = min(3, len(blocos))
    per_page = n_cols * 2
    paginas = [blocos[i:i+per_page] for i in range(0, len(blocos), per_page)]
    for p_i, pag in enumerate(paginas):
        fig = _figura_ff(pag, n_cols)
        titulo = "Forças e Fraquezas"
        if len(paginas) > 1:
            titulo += f"  ({p_i+1}/{len(paginas)})"
        fig.suptitle(titulo, fontsize=13, fontweight="bold", y=0.99)
        fig.tight_layout(rect=[0, 0, 1, 0.96])
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)


# ---------------------------------------------------------------------------
# Seção 4: % de Insatisfeitos
# ---------------------------------------------------------------------------
def _sec_insatisfeitos(pdf, ctx):
    df_display = ctx["df_display"]
    colunas_finais = ctx["colunas_finais"]
    dados = ctx["dados"]

    df_pessoas = dados["df_pessoas"]
    df_respostas = dados["df_respostas"]
    perguntas = dados["perguntas"]
    nos = dados.get("nos")

    status_col = next(
        (c for c in df_respostas.columns if c.strip().lower() == "status"), None
    )
    df_fin = (
        df_respostas[df_respostas[status_col].astype(str).str.strip().str.upper() == "FINISHED"]
        if status_col else df_respostas
    )

    cats = [r for r in df_display.index if r not in _METRICAS_FIXAS]
    pergs_por_cat = {
        cat: [p for p in perguntas if p.categoria == cat and p.tipo != "nps"]
        for cat in cats
    }

    rows = []
    for cfg, col_label in zip(colunas_finais, df_display.columns):
        cods = filtrar_pessoas(df_pessoas, cfg.get("area"), cfg.get("filtros", {}), nos=nos)
        df_col = df_fin[df_fin["cod_ajuste"].isin(cods)]
        for cat in cats:
            pergs = pergs_por_cat.get(cat, [])
            if not pergs:
                continue
            valores = []
            for p in pergs:
                if p.col_resp not in df_col.columns:
                    continue
                vs = pd.to_numeric(df_col[p.col_resp], errors="coerce").dropna().tolist()
                valores.extend(vs)
            if len(valores) < MIN_RESPONDENTES:
                continue
            arr = np.array(valores, dtype=float)
            pct = float(np.mean(arr <= _LIMIAR_INSATISFEITO) * 100)
            nota = df_display.loc[cat, col_label]
            rows.append({
                "Coluna": col_label,
                "Categoria": cat,
                "Nota média": round(float(nota), 2) if pd.notna(nota) else None,
                "% insatisfeitos": round(pct, 1),
            })

    if not rows:
        return

    df_result = pd.DataFrame(rows)
    MAX_ROWS = 35
    chunks = [df_result.iloc[i:i+MAX_ROWS] for i in range(0, len(df_result), MAX_ROWS)]

    for ch_i, chunk in enumerate(chunks):
        pct_idx = list(chunk.columns).index("% insatisfeitos")
        cell_text, cell_colors = [], []
        for _, row in chunk.iterrows():
            row_t = [str(v) if pd.notna(v) else "—" for v in row.values]
            try:
                pct_f = float(row["% insatisfeitos"])
            except Exception:
                pct_f = 0.0
            bg = _rgn(1.0 - min(1.0, pct_f / 50))
            row_c = [(0.95, 0.95, 0.95)] * len(chunk.columns)
            row_c[pct_idx] = bg
            cell_text.append(row_t); cell_colors.append(row_c)

        fig_h = max(6.0, len(chunk)*0.48 + 1.8)
        fig, ax = plt.subplots(figsize=(10, fig_h))
        ax.axis("off")
        tbl = ax.table(
            cellText=cell_text, colLabels=list(chunk.columns),
            cellColours=cell_colors, loc="center", cellLoc="center",
        )
        tbl.auto_set_font_size(False); tbl.set_fontsize(8); tbl.scale(1, 2.1)
        for j in range(len(chunk.columns)):
            tbl[(0, j)].set_facecolor((0.84, 0.84, 0.84))
            tbl[(0, j)].get_text().set_fontweight("bold")

        suffix = f"  (parte {ch_i+1}/{len(chunks)})" if len(chunks) > 1 else ""
        ax.set_title(
            f"% de Insatisfeitos  (Likert ≤ {_LIMIAR_INSATISFEITO}){suffix}",
            fontsize=13, fontweight="bold", pad=20,
        )
        pdf.savefig(fig, bbox_inches="tight")
        plt.close(fig)


# ---------------------------------------------------------------------------
# Seção 5: Ranking por categoria
# ---------------------------------------------------------------------------
def _sec_ranking(pdf, ctx):
    df_display = ctx["df_display"]
    df_meta = ctx["df_meta"]
    cat_sel = ctx.get("cat_ranking")

    cats = [r for r in df_display.index if r not in _METRICAS_FIXAS]
    if not cat_sel or cat_sel not in df_display.index:
        if not cats:
            return
        cat_sel = cats[0]
        nota = f"(categoria selecionada na tela não disponível — exibindo: {cat_sel})"
    else:
        nota = None

    row = df_display.loc[cat_sel].dropna().sort_values(ascending=False)
    if row.empty:
        return

    all_notas = df_display.loc[cats].values.flatten() if cats else np.array([])
    all_notas = all_notas[~pd.isna(all_notas)].astype(float)
    nota_min = float(all_notas.min()) if len(all_notas) > 0 else 0.0
    nota_max = float(all_notas.max()) if len(all_notas) > 0 else 100.0
    span = nota_max - nota_min if nota_max != nota_min else 1.0

    colors = [_rgn((float(v)-nota_min)/span) for v in row.values]

    fig, ax = plt.subplots(figsize=(max(10, len(row)*1.6+2), 5.5))
    ax.bar(range(len(row)), row.values, color=colors, edgecolor="white", linewidth=0.5)
    for i, (col, val) in enumerate(zip(row.index, row.values)):
        ax.text(i, val+0.5, f"{val:.1f}", ha="center", va="bottom",
                fontsize=9, fontweight="bold")

    labels = [c[:30]+"…" if len(c) > 30 else c for c in row.index]
    ax.set_xticks(range(len(row))); ax.set_xticklabels(labels, rotation=-30, ha="left", fontsize=8)
    ax.set_ylim(0, min(105, nota_max*1.18))
    ax.set_ylabel("Nota"); ax.spines["top"].set_visible(False); ax.spines["right"].set_visible(False)
    ax.set_facecolor("white")
    titulo = f"Ranking — {cat_sel}"
    if nota:
        titulo += f"\n{nota}"
    ax.set_title(titulo, fontsize=12, fontweight="bold")
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Seção 6: Qualidade dos dados
# ---------------------------------------------------------------------------
def _sec_qualidade(pdf, ctx):
    df_pessoas = ctx["dados"]["df_pessoas"]
    limiar = ctx.get("limiar_faltante", 0.10)
    atributos = ctx.get("atributos_recorte", [])
    if not atributos:
        return

    rows = []
    total = len(df_pessoas)
    for attr in atributos:
        if attr not in df_pessoas.columns or total == 0:
            continue
        n_falt = int(
            df_pessoas[attr].isna().sum()
            + df_pessoas[attr].astype(str).str.strip().isin(["", "nan", "None"]).sum()
        )
        pct = n_falt / total * 100
        rows.append({
            "Atributo": attr,
            "Total": total,
            "Faltantes": n_falt,
            "% faltante": round(pct, 1),
            "Alerta": "⚠️" if pct > limiar*100 else "",
        })
    if not rows:
        return

    df_q = pd.DataFrame(rows)
    cell_text = df_q.astype(str).values.tolist()
    cell_colors = []
    for _, row in df_q.iterrows():
        bg = (1.0, 0.88, 0.77) if row["Alerta"] == "⚠️" else (0.95, 0.95, 0.95)
        cell_colors.append([bg]*len(df_q.columns))

    fig_h = max(5.0, len(df_q)*0.55+1.8)
    fig, ax = plt.subplots(figsize=(10, fig_h))
    ax.axis("off")
    tbl = ax.table(
        cellText=cell_text, colLabels=list(df_q.columns),
        cellColours=cell_colors, loc="center", cellLoc="center",
    )
    tbl.auto_set_font_size(False); tbl.set_fontsize(8.5); tbl.scale(1, 2.2)
    for j in range(len(df_q.columns)):
        tbl[(0, j)].set_facecolor((0.84, 0.84, 0.84))
        tbl[(0, j)].get_text().set_fontweight("bold")

    ax.set_title(
        f"Qualidade dos Dados  (alerta: % faltante > {limiar*100:.0f}%)",
        fontsize=13, fontweight="bold", pad=20,
    )
    pdf.savefig(fig, bbox_inches="tight")
    plt.close(fig)


# ---------------------------------------------------------------------------
# Ponto de entrada público
# ---------------------------------------------------------------------------
def gerar_relatorio_pdf(secoes: list, ctx: dict) -> bytes:
    """
    Gera PDF com as seções selecionadas.

    ctx deve conter:
        df_display, df_meta, colunas_labels, colunas_finais, dados,
        fig_plotly (Plotly Figure ou None),
        cat_ranking (str ou None),
        limiar_faltante (float),
        atributos_recorte (list[str])
    """
    buf = io.BytesIO()
    with PdfPages(buf) as pdf:
        _capa(pdf, secoes, ctx)

        if "tabela" in secoes:
            _sec_tabela(pdf, ctx)
        if "heatmap" in secoes:
            _sec_heatmap(pdf, ctx)
        if "forcas_fraquezas" in secoes:
            _sec_ff(pdf, ctx)
        if "insatisfeitos" in secoes:
            _sec_insatisfeitos(pdf, ctx)
        if "ranking" in secoes:
            _sec_ranking(pdf, ctx)
        if "qualidade" in secoes:
            _sec_qualidade(pdf, ctx)

    return buf.getvalue()
