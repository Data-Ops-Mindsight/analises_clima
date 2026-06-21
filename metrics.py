"""
metrics.py — Cálculo de notas por pergunta, categoria e métricas fixas.
Funções puras e testáveis, sem dependência de Streamlit.
"""

import pandas as pd
import numpy as np
from typing import Optional
from data_loading import Pergunta, pessoas_da_area, pessoas_do_caminho, ATRIBUTOS_RECORTE

# Flag de configuração: como tratar NPS na média da categoria
# "cru"        → NPS (-100..+100) e Likert (0..100) entram direto na média
# "normalizado" → NPS é convertido: (nps + 100) / 2  antes de entrar na média
NPS_NA_MEDIA_DA_CATEGORIA = "cru"

# Número mínimo de respondentes para exibir valor (privacidade)
MIN_RESPONDENTES = 3


# ---------------------------------------------------------------------------
# Helpers NPS
# ---------------------------------------------------------------------------

def calcular_nps(valores: pd.Series) -> Optional[float]:
    """
    Fórmula NPS clássica: % promotores (9-10) − % detratores (0-6).
    Resultado em −100..+100. Retorna None se não houver respondentes.
    """
    vals = pd.to_numeric(valores, errors="coerce").dropna()
    n = len(vals)
    if n == 0:
        return None
    promotores = (vals >= 9).sum()
    detratores = (vals <= 6).sum()
    return float((promotores - detratores) / n * 100)


# ---------------------------------------------------------------------------
# Nota por pergunta (para um conjunto de respondentes)
# ---------------------------------------------------------------------------

def nota_pergunta(
    pergunta: Pergunta,
    df_respostas: pd.DataFrame,
    cods: pd.Series,
) -> Optional[float]:
    """
    Calcula a nota de uma pergunta para o conjunto de cod_ajuste fornecido.
    Retorna None se não há dados suficientes.
    """
    df_sub = df_respostas[df_respostas["cod_ajuste"].isin(cods)]
    status_col = next(
        (c for c in df_sub.columns if c.strip().lower() == "status"), None
    )
    if status_col:
        df_sub = df_sub[
            df_sub[status_col].astype(str).str.strip().str.upper() == "FINISHED"
        ]
    vals = pd.to_numeric(df_sub[pergunta.col_resp], errors="coerce").dropna()

    if len(vals) == 0:
        return None

    if pergunta.tipo == "nps":
        return calcular_nps(vals)
    else:
        return float(vals.mean())


# ---------------------------------------------------------------------------
# Nota por categoria
# ---------------------------------------------------------------------------

def nota_categoria(
    categoria: str,
    perguntas: list[Pergunta],
    df_respostas: pd.DataFrame,
    cods: pd.Series,
) -> Optional[float]:
    """
    Média das notas das perguntas da categoria para o conjunto de respondentes.
    """
    pergs_cat = [p for p in perguntas if p.categoria == categoria]
    notas = []
    for p in pergs_cat:
        nota = nota_pergunta(p, df_respostas, cods)
        if nota is not None:
            if p.tipo == "nps" and NPS_NA_MEDIA_DA_CATEGORIA == "normalizado":
                nota = (nota + 100) / 2
            notas.append(nota)
    if not notas:
        return None
    return float(np.mean(notas))


# ---------------------------------------------------------------------------
# Filtragem de pessoas
# ---------------------------------------------------------------------------

def filtrar_pessoas(
    df_pessoas: pd.DataFrame,
    caminho: Optional[str],
    filtros: Optional[dict] = None,
    nos: Optional[dict] = None,
) -> pd.Series:
    """
    Retorna a Series de cod_ajuste para o caminho + filtros opcionais.
    caminho=None → empresa toda.
    nos: dicionário {caminho: NoInfo} retornado por construir_caminhos().
    filtros = {atributo: [valor1, valor2, ...]}
    """
    if caminho is None:
        df = df_pessoas.copy()
    elif nos is not None and caminho in nos:
        # Filtro por caminho exato (inclui toda sub-árvore via frozenset de cods)
        df = df_pessoas[df_pessoas["cod_ajuste"].isin(nos[caminho].cods)]
    else:
        # Fallback: compatibilidade com chamadas antigas que passam nome simples
        cods_area = pessoas_da_area(df_pessoas, caminho)
        df = df_pessoas[df_pessoas["cod_ajuste"].isin(cods_area)]

    if filtros:
        for attr, valores in filtros.items():
            if attr in df.columns and valores:
                df = df[df[attr].astype(str).str.strip().isin([str(v).strip() for v in valores])]

    return df["cod_ajuste"].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Respondentes vs participantes
# ---------------------------------------------------------------------------

def contar_respondentes(df_respostas: pd.DataFrame, cods: pd.Series) -> int:
    """
    Conta respondentes válidos dentro de 'cods'.
    Se existir coluna 'status', usa somente linhas com status == FINISHED.
    Caso contrário (fallback), usa ao menos uma resposta numérica não-nula.
    """
    df_sub = df_respostas[df_respostas["cod_ajuste"].isin(cods)]
    status_col = next(
        (c for c in df_sub.columns if c.strip().lower() == "status"), None
    )
    if status_col:
        mask = df_sub[status_col].astype(str).str.strip().str.upper() == "FINISHED"
    else:
        cols_resp = [c for c in df_sub.columns if c != "cod_ajuste"]
        mask = df_sub[cols_resp].apply(pd.to_numeric, errors="coerce").notna().any(axis=1)
    return int(mask.sum())


def calcular_adesao(participantes: int, respondentes: int) -> Optional[float]:
    """% de adesão."""
    if participantes == 0:
        return None
    return respondentes / participantes * 100


# ---------------------------------------------------------------------------
# Cálculo completo de uma coluna do mapa
# ---------------------------------------------------------------------------

def calcular_coluna(
    label: str,
    cods: pd.Series,
    df_respostas: pd.DataFrame,
    perguntas: list[Pergunta],
    categorias: list[str],
    df_pessoas: pd.DataFrame,
) -> dict:
    """
    Calcula todas as linhas do mapa para uma coluna definida por 'cods'.
    Retorna dict com chaves = nomes das linhas e valores = notas.
    """
    participantes = len(cods)
    respondentes = contar_respondentes(df_respostas, cods)

    resultado = {
        "label": label,
        "participantes": participantes,
        "respondentes": respondentes,
        "abaixo_minimo": respondentes < MIN_RESPONDENTES,
    }

    # Métricas fixas
    perg_enps = next((p for p in perguntas if p.id == 49), None)
    perg_lnps = next((p for p in perguntas if p.id == 51), None)

    resultado["ENPS"] = nota_pergunta(perg_enps, df_respostas, cods) if perg_enps else None
    resultado["LNPS"] = nota_pergunta(perg_lnps, df_respostas, cods) if perg_lnps else None
    resultado["Adesão (%)"] = calcular_adesao(participantes, respondentes)

    # Engajamento Geral (categoria fixa no topo)
    resultado["Engajamento Geral"] = nota_categoria(
        "Engajamento Geral", perguntas, df_respostas, cods
    )

    # Demais categorias
    for cat in categorias:
        if cat == "Engajamento Geral":
            continue  # já calculado acima
        resultado[cat] = nota_categoria(cat, perguntas, df_respostas, cods)

    return resultado


# ---------------------------------------------------------------------------
# Montar o DataFrame do mapa de calor
# ---------------------------------------------------------------------------

def montar_mapa(
    colunas_config: list[dict],
    dados: dict,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """
    Recebe lista de configurações de colunas e o dicionário de dados carregados.
    Retorna (df_mapa, df_meta) onde:
      - df_mapa: linhas = métricas/categorias, colunas = labels das colunas
      - df_meta: linhas = ['participantes', 'respondentes', 'abaixo_minimo'],
                 colunas = labels
    """
    df_pessoas = dados["df_pessoas"]
    df_respostas = dados["df_respostas"]
    perguntas = dados["perguntas"]

    # Extrair categorias únicas na ordem encontrada nos dados
    cats_vistas = []
    cats_set = set()
    for p in perguntas:
        if p.categoria not in cats_set:
            cats_vistas.append(p.categoria)
            cats_set.add(p.categoria)

    nos = dados.get("nos")

    resultados = []
    for cfg in colunas_config:
        label = cfg.get("label", "")
        area = cfg.get("area", None)   # None → empresa toda (caminho ou None)
        filtros = cfg.get("filtros", {})

        cods = filtrar_pessoas(df_pessoas, area, filtros, nos=nos)
        resultado = calcular_coluna(
            label=label,
            cods=cods,
            df_respostas=df_respostas,
            perguntas=perguntas,
            categorias=cats_vistas,
            df_pessoas=df_pessoas,
        )
        resultados.append(resultado)

    if not resultados:
        return pd.DataFrame(), pd.DataFrame()

    # Ordem das linhas: métricas fixas no topo, depois categorias
    metricas_fixas = ["Engajamento Geral", "ENPS", "LNPS", "Adesão (%)"]
    categorias_restantes = [c for c in cats_vistas if c not in metricas_fixas]

    linhas_ordem = metricas_fixas + categorias_restantes
    labels = [r["label"] for r in resultados]

    dados_mapa = {}
    for linha in linhas_ordem:
        dados_mapa[linha] = [r.get(linha) for r in resultados]

    df_mapa = pd.DataFrame(dados_mapa, index=labels).T

    dados_meta = {
        "participantes": [r["participantes"] for r in resultados],
        "respondentes": [r["respondentes"] for r in resultados],
        "abaixo_minimo": [r["abaixo_minimo"] for r in resultados],
    }
    df_meta = pd.DataFrame(dados_meta, index=labels).T

    return df_mapa, df_meta


# ---------------------------------------------------------------------------
# Gerar colunas por quebra
# ---------------------------------------------------------------------------

def gerar_colunas_quebra(
    area_base: Optional[str],
    atributo_quebra: str,
    valores_selecionados: Optional[list],
    df_pessoas: pd.DataFrame,
    label_prefixo: str = "",
    nos: Optional[dict] = None,
) -> list[dict]:
    """
    Gera uma lista de configurações de colunas para cada valor distinto
    do atributo de quebra dentro da área base (identificada por caminho).
    """
    if area_base is None:
        df = df_pessoas.copy()
    elif nos is not None and area_base in nos:
        df = df_pessoas[df_pessoas["cod_ajuste"].isin(nos[area_base].cods)]
    else:
        from data_loading import pessoas_da_area
        cods_area = pessoas_da_area(df_pessoas, area_base)
        df = df_pessoas[df_pessoas["cod_ajuste"].isin(cods_area)]

    if atributo_quebra not in df.columns:
        return []

    valores_disponiveis = sorted(
        df[atributo_quebra].dropna().astype(str).str.strip().unique().tolist()
    )
    valores_disponiveis = [v for v in valores_disponiveis if v.lower() not in ("nan", "none", "")]

    if valores_selecionados:
        valores_usar = [v for v in valores_selecionados if v in valores_disponiveis]
    else:
        valores_usar = valores_disponiveis

    colunas = []
    for val in valores_usar:
        label = f"{label_prefixo} — {val}" if label_prefixo else val
        colunas.append({
            "label": label,
            "area": area_base,  # agora é um caminho completo ou None
            "filtros": {atributo_quebra: [val]},
        })
    return colunas
