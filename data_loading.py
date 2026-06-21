"""
data_loading.py — Carga e parsing do arquivo Excel de pesquisa de clima.
"""

from __future__ import annotations

import pandas as pd
import streamlit as st
from typing import NamedTuple

# IDs das perguntas NPS (apoio à detecção automática)
IDS_NPS = {49, 50, 51}

# ---------------------------------------------------------------------------
# Normalização de nomes de nós (item 2 — unificação de grafias)
# ---------------------------------------------------------------------------
# Chave: string que deve ser substituída (comparada em lowercase + strip).
# Valor: grafia canônica a usar.
NORMALIZACAO_NOS = {
    "la mano": "La Mano",
    # Adicionar outros casos aqui se surgirem (ex: "sdrs": "SDRs")
}


def _normalizar_no(valor) -> str:
    """Aplica o mapa de normalização a um valor de nó (case-insensitive).
    Robusto a pd.NA, None e strings vazias (backends NumPy e Arrow)."""
    if valor is None:
        return valor
    if not isinstance(valor, str):
        try:
            if pd.isna(valor):
                return valor
        except (TypeError, ValueError):
            pass
    s = str(valor).strip()
    if s == "" or s.lower() in ("nan", "none", "<na>"):
        return valor
    return NORMALIZACAO_NOS.get(s.lower(), s)


def normalizar_coluna_nos(serie: pd.Series) -> pd.Series:
    """Aplica _normalizar_no a todos os valores não-nulos de uma Series.
    na_action='ignore' garante que nulos (NaN, pd.NA) nunca chegam à função."""
    return serie.map(_normalizar_no, na_action="ignore")


# ---------------------------------------------------------------------------
# Estrutura de nó de caminho
# ---------------------------------------------------------------------------

class NoInfo(NamedTuple):
    caminho: str          # "N1 › N2 › N3"  — identidade única
    nome: str             # só o nó folha,  ex: "CWB"
    pai: str | None       # nome do pai imediato,  ex: "Assessoria"
    nivel: str            # "N1" | "N2" | "N3" | "N4"
    cods: frozenset       # cod_ajuste de TODAS as pessoas desse nó e sub-árvore


SEP = " › "  # separador de caminho

# ---------------------------------------------------------------------------
# Parsing de perguntas
# ---------------------------------------------------------------------------

class Pergunta(NamedTuple):
    id: int
    nome: str
    col_id: str
    col_resp: str
    tipo: str
    categoria: str


def nao_likert_candidatos(vals: set) -> set:
    likert_vals = {0, 25, 50, 75, 100}
    return {v for v in vals if isinstance(v, (int, float)) and v not in likert_vals}


def classificar_tipo(pergunta_id: int, valores_observados: pd.Series) -> str:
    if pergunta_id in IDS_NPS:
        return "nps"
    vals = set(valores_observados.dropna().unique())
    nao_likert = nao_likert_candidatos(vals)
    indicadores_nps = {v for v in nao_likert if isinstance(v, (int, float)) and 1 <= v <= 10}
    if indicadores_nps:
        return "nps"
    return "likert"


def parsear_perguntas(df_respostas: pd.DataFrame) -> list[Pergunta]:
    """Detecta pares (col_id, col_resp) e classifica cada pergunta."""
    perguntas = []
    colunas = list(df_respostas.columns)
    i = 0
    while i < len(colunas) - 1:
        col_atual = colunas[i]
        col_prox = colunas[i + 1]

        if "-ID-Categoria" in str(col_atual):
            col_id = col_atual
            col_resp = col_prox
            try:
                perg_id = int(str(col_atual).split("-")[0])
            except (ValueError, IndexError):
                i += 2
                continue

            valores_id = df_respostas[col_id].dropna()
            if valores_id.empty:
                i += 2
                continue

            partes = str(valores_id.iloc[0]).split("-", 1)
            if len(partes) < 2:
                i += 2
                continue
            categoria = partes[1].strip()

            vals_numericos = pd.to_numeric(df_respostas[col_resp], errors="coerce")
            if vals_numericos.notna().mean() < 0.1:
                i += 2
                continue

            tipo = classificar_tipo(perg_id, vals_numericos)
            perguntas.append(Pergunta(
                id=perg_id,
                nome=f"{perg_id}-{categoria}",
                col_id=col_id,
                col_resp=col_resp,
                tipo=tipo,
                categoria=categoria,
            ))
            i += 2
        else:
            i += 1

    return perguntas


# ---------------------------------------------------------------------------
# Construção de caminhos hierárquicos (item 1)
# ---------------------------------------------------------------------------

def construir_caminhos(df_pessoas: pd.DataFrame) -> dict[str, NoInfo]:
    """
    Percorre cada pessoa e constrói todos os nós distintos como caminhos completos.
    Retorna {caminho: NoInfo}, onde caminho é a identidade única de cada nó.
    Os cods em cada NoInfo são a união de TODOS os cod_ajuste cujo caminho
    começa com o prefixo desse nó (ou seja, inclui toda a sub-árvore).
    """
    niveis = [c for c in ["N1", "N2", "N3", "N4"] if c in df_pessoas.columns]

    # Primeiro passo: para cada pessoa, derivar todos os caminhos de ancestral
    # e associar o cod_ajuste a todos eles.
    # nos_cods[caminho] = set de cod_ajuste que PERTENCEM a esse nó ou abaixo
    nos_cods: dict[str, set] = {}
    nos_meta: dict[str, tuple] = {}  # caminho → (nome, pai, nivel)

    for _, row in df_pessoas.iterrows():
        cod = str(row["cod_ajuste"])
        ancestrais = []
        for nv in niveis:
            val = row.get(nv)
            if pd.isna(val) or str(val).strip() == "":
                break
            nome_no = str(val).strip()
            pai = ancestrais[-1] if ancestrais else None
            ancestrais.append(nome_no)

            caminho = SEP.join(ancestrais)
            if caminho not in nos_cods:
                nos_cods[caminho] = set()
                nos_meta[caminho] = (nome_no, pai, nv)
            nos_cods[caminho].add(cod)

    # Segundo passo: propagar cods de filhos para ancestrais
    # (um nó já acumula seus próprios filhos porque iteramos pessoa a pessoa,
    # cada pessoa adiciona seu cod_ajuste a TODOS os ancestrais dela)

    resultado = {}
    for caminho, cods in nos_cods.items():
        nome_no, pai, nivel = nos_meta[caminho]
        resultado[caminho] = NoInfo(
            caminho=caminho,
            nome=nome_no,
            pai=pai,
            nivel=nivel,
            cods=frozenset(cods),
        )

    return resultado


def detectar_ambiguidades(nos: dict[str, NoInfo]) -> set[str]:
    """
    Retorna os nomes de nós que aparecem em mais de um caminho distinto.
    Usa contagem de caminhos (não de nomes de pais) para capturar casos onde
    dois caminhos distintos têm o mesmo pai imediato após normalização.
    """
    from collections import Counter
    contagem = Counter(info.nome for info in nos.values())
    return {nome for nome, count in contagem.items() if count > 1}


def rotulo_curto(info: NoInfo, nos: dict[str, NoInfo]) -> str:
    """
    Rótulo curto para exibição no mapa.
    - Nó não-ambíguo → só o nome.
    - Nó ambíguo → sobe na hierarquia até encontrar o ancestral que o distingue
      de todos os outros nós com o mesmo nome. Ex: se dois "Truckers" têm o mesmo
      pai imediato "La Mano", sobe mais um nível e usa "Assessoria"/"Formação".
    """
    outros_caminhos = [n.caminho for c, n in nos.items()
                       if n.nome == info.nome and c != info.caminho]
    if not outros_caminhos:
        return info.nome  # único, sem desambiguação

    partes_proprio = info.caminho.split(SEP)
    outros_partes = [c.split(SEP) for c in outros_caminhos]

    # Tenta adicionar o ancestral mais próximo (depth=1 = pai, 2 = avô, …)
    for depth in range(1, len(partes_proprio)):
        idx = -(depth + 1)
        if abs(idx) > len(partes_proprio):
            break
        candidato = partes_proprio[idx]
        outros_candidatos = {op[idx] for op in outros_partes if len(op) >= abs(idx)}
        if candidato not in outros_candidatos:
            return f"{info.nome} ({candidato})"

    return info.caminho  # fallback: caminho completo (caso não discriminado)


def pessoas_do_caminho(df_pessoas: pd.DataFrame, nos: dict[str, NoInfo], caminho: str) -> pd.Series:
    """Retorna a Series de cod_ajuste de todas as pessoas no nó e sua sub-árvore."""
    if caminho not in nos:
        return pd.Series(dtype=str)
    cods = nos[caminho].cods
    return df_pessoas.loc[df_pessoas["cod_ajuste"].isin(cods), "cod_ajuste"].reset_index(drop=True)


# ---------------------------------------------------------------------------
# Mantido para retrocompatibilidade interna (usado em gerar_colunas_quebra)
# ---------------------------------------------------------------------------

def pessoas_da_area(df_pessoas: pd.DataFrame, area: str) -> pd.Index:
    """Filtra pessoas cujo caminho *começa* com 'area' (qualquer nível)."""
    mask = pd.Series(False, index=df_pessoas.index)
    for nivel in ["N1", "N2", "N3", "N4"]:
        if nivel in df_pessoas.columns:
            mask = mask | (df_pessoas[nivel].astype(str).str.strip() == str(area).strip())
    return df_pessoas.loc[mask, "cod_ajuste"]


ATRIBUTOS_RECORTE = [
    "Tipo de Contrato",
    "Local de trabalho",
    "GRAU DE INSTRUÇÃO",
    "Gênero",
    "Senioridade",
    "Liderança (sim?)",
]


# ---------------------------------------------------------------------------
# Carga principal
# ---------------------------------------------------------------------------

@st.cache_data(show_spinner="Carregando dados...")
def carregar_dados(arquivo) -> dict:
    xls = pd.ExcelFile(arquivo)

    # --- Pessoas ---
    df_pessoas = xls.parse("Anon - Pessoas")
    df_pessoas.columns = df_pessoas.columns.str.strip()
    df_pessoas["cod_ajuste"] = df_pessoas["cod_ajuste"].astype(str).str.strip()

    # Normalizar grafias nas colunas de hierarquia (antes de tudo)
    for nivel in ["N1", "N2", "N3", "N4"]:
        if nivel in df_pessoas.columns:
            df_pessoas[nivel] = normalizar_coluna_nos(df_pessoas[nivel])

    # --- Respostas ---
    df_respostas = xls.parse("Anon - Respostas")
    df_respostas.columns = df_respostas.columns.str.strip()
    df_respostas["cod_ajuste"] = df_respostas["cod_ajuste"].astype(str).str.strip()

    # --- eNPS / lNPS / Categorias ---
    df_enps = xls.parse("eNPS"); df_enps.columns = df_enps.columns.str.strip()
    df_lnps = xls.parse("lNPS"); df_lnps.columns = df_lnps.columns.str.strip()
    df_cats = xls.parse("Categorias"); df_cats.columns = df_cats.columns.str.strip()

    # --- Parsing de perguntas ---
    perguntas = parsear_perguntas(df_respostas)

    # --- Caminhos hierárquicos ---
    nos = construir_caminhos(df_pessoas)
    ambiguos = detectar_ambiguidades(nos)

    # Lista ordenada de caminhos para o seletor
    caminhos_ordenados = sorted(nos.keys())

    # Atributos de recorte com valores únicos (empresa toda)
    atributos_disponiveis = {}
    for attr in ATRIBUTOS_RECORTE:
        if attr in df_pessoas.columns:
            vals = sorted(df_pessoas[attr].dropna().astype(str).str.strip().unique().tolist())
            vals = [v for v in vals if v and v.lower() not in ("nan", "none", "")]
            if vals:
                atributos_disponiveis[attr] = vals

    return {
        "df_pessoas": df_pessoas,
        "df_respostas": df_respostas,
        "df_enps": df_enps,
        "df_lnps": df_lnps,
        "df_cats": df_cats,
        "perguntas": perguntas,
        # estruturas de caminho
        "nos": nos,
        "ambiguos": ambiguos,
        "caminhos_ordenados": caminhos_ordenados,
        # legado — mantido para não quebrar validação
        "arvore": {},
        "mapa_nivel": {},
        "todas_areas": caminhos_ordenados,
        "atributos_disponiveis": atributos_disponiveis,
    }
