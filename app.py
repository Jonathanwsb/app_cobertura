import io
import re
import unicodedata

import geopandas as gpd
import pandas as pd
import numpy as np
import pydeck as pdk
import streamlit as st

st.set_page_config(page_title="Cobertura de Esgoto - Buffer 15m", layout="wide")

BUFFER_M = 15
TREAT_COL_CANDIDATES = ["Tratamento", "TRATAMENTO", "tratamento"]
TREAT_VALUE = "Sim"
MAX_PONTOS_MAPA = 40000  # limite de pontos plotados no mapa (performance do navegador)

# Cores RGBA para o mapa
COR_COBERTO_TRATAMENTO = [34, 139, 34, 160]     # verde - coberto por rede COM tratamento
COR_COBERTO_SEM_TRATAMENTO = [255, 165, 0, 160]  # laranja - coberto só por rede SEM tratamento
COR_NAO_COBERTO = [220, 20, 60, 130]             # vermelho - não coberto
COR_REDE_TRATAMENTO = [0, 100, 0, 220]           # verde escuro - linha de rede tratada
COR_REDE_SEM_TRATAMENTO = [120, 120, 120, 180]   # cinza - linha de rede sem tratamento


# ----------------------------------------------------------------------
# Utilidades
# ----------------------------------------------------------------------
def normalizar_nome(nome: str) -> str:
    """Remove prefixos conhecidos, acentos e caracteres especiais para
    permitir o pareamento entre arquivo de rede e arquivo de CNEFE."""
    nome = re.sub(r"\.gpkg$", "", nome, flags=re.IGNORECASE)
    nome = re.sub(r"^(NM_MUN_|CNEFE_)", "", nome, flags=re.IGNORECASE)
    nome = nome.replace("_", " ").strip()
    nome = unicodedata.normalize("NFKD", nome).encode("ascii", "ignore").decode("ascii")
    nome = re.sub(r"\s+", " ", nome).strip().lower()
    return nome


def encontrar_coluna_tratamento(gdf: gpd.GeoDataFrame):
    for col in TREAT_COL_CANDIDATES:
        if col in gdf.columns:
            return col
    return None


def processar_par(nome_municipio: str, rede_bytes: bytes, cnefe_bytes: bytes):
    """Processa um par (rede, cnefe). Retorna (dict de resultados, gdf cnefe
    classificado em EPSG:4326, gdf rede em EPSG:4326)."""
    rede = gpd.read_file(io.BytesIO(rede_bytes), driver="GPKG")
    cnefe = gpd.read_file(io.BytesIO(cnefe_bytes), driver="GPKG")

    if rede.crs is None:
        raise ValueError("Camada de rede sem CRS definido.")

    # Reprojeta CNEFE para o CRS métrico da rede (necessário p/ buffer em metros)
    if cnefe.crs != rede.crs:
        cnefe = cnefe.to_crs(rede.crs)

    total_pontos = len(cnefe)

    # --- Rede total ---
    buffer_total = rede.geometry.buffer(BUFFER_M).union_all()
    dentro_total = cnefe.within(buffer_total)
    qtd_total = int(dentro_total.sum())

    # --- Rede com tratamento ---
    col_trat = encontrar_coluna_tratamento(rede)
    if col_trat is not None:
        rede_trat = rede[rede[col_trat].astype(str).str.strip().str.lower() == TREAT_VALUE.lower()]
        if len(rede_trat) > 0:
            buffer_trat = rede_trat.geometry.buffer(BUFFER_M).union_all()
            dentro_trat = cnefe.within(buffer_trat)
            qtd_trat = int(dentro_trat.sum())
        else:
            dentro_trat = pd.Series(False, index=cnefe.index)
            qtd_trat = 0
    else:
        dentro_trat = pd.Series(False, index=cnefe.index)
        qtd_trat = None

    resultado = {
        "Município": nome_municipio.title(),
        "Pontos CNEFE (total)": total_pontos,
        "Cobertos - Rede Total": qtd_total,
        "% Rede Total": round(100 * qtd_total / total_pontos, 2) if total_pontos else 0,
        "Cobertos - Rede c/ Tratamento": qtd_trat,
        "% Rede c/ Tratamento": round(100 * qtd_trat / total_pontos, 2) if (total_pontos and qtd_trat is not None) else None,
        "Segmentos de Rede": len(rede),
        "Coluna Tratamento encontrada": col_trat if col_trat else "NÃO ENCONTRADA",
    }

    # Classificação por ponto, para o mapa
    cnefe = cnefe.copy()
    cnefe["coberto_total"] = dentro_total.values
    cnefe["coberto_tratamento"] = dentro_trat.values
    cnefe_4326 = cnefe.to_crs(4326)
    rede_4326 = rede.to_crs(4326)

    return resultado, cnefe_4326, rede_4326


def categoria_cor(row):
    if row["coberto_tratamento"]:
        return COR_COBERTO_TRATAMENTO
    elif row["coberto_total"]:
        return COR_COBERTO_SEM_TRATAMENTO
    else:
        return COR_NAO_COBERTO


def montar_mapa(cnefe_4326: gpd.GeoDataFrame, rede_4326: gpd.GeoDataFrame, col_trat: str | None):
    # Amostra pontos se necessário (performance no navegador)
    if len(cnefe_4326) > MAX_PONTOS_MAPA:
        cnefe_amostra = cnefe_4326.sample(MAX_PONTOS_MAPA, random_state=42)
        amostrado = True
    else:
        cnefe_amostra = cnefe_4326
        amostrado = False

    pontos_df = pd.DataFrame({
        "lon": cnefe_amostra.geometry.x,
        "lat": cnefe_amostra.geometry.y,
        "cor": cnefe_amostra.apply(categoria_cor, axis=1),
    })

    layer_pontos = pdk.Layer(
        "ScatterplotLayer",
        data=pontos_df,
        get_position=["lon", "lat"],
        get_fill_color="cor",
        get_radius=6,
        radius_min_pixels=2,
        radius_max_pixels=8,
        pickable=False,
    )

    # Linhas da rede
    def linha_coords(geom):
        if geom.geom_type == "MultiLineString":
            return [list(line.coords) for line in geom.geoms]
        return [list(geom.coords)]

    linhas = []
    for _, row in rede_4326.iterrows():
        tratada = col_trat is not None and str(row.get(col_trat, "")).strip().lower() == TREAT_VALUE.lower()
        cor = COR_REDE_TRATAMENTO if tratada else COR_REDE_SEM_TRATAMENTO
        for coords in linha_coords(row.geometry):
            linhas.append({"path": [[c[0], c[1]] for c in coords], "cor": cor})

    layer_rede = pdk.Layer(
        "PathLayer",
        data=pd.DataFrame(linhas),
        get_path="path",
        get_color="cor",
        get_width=3,
        width_min_pixels=1,
        pickable=False,
    )

    centro_lat = cnefe_4326.geometry.y.mean()
    centro_lon = cnefe_4326.geometry.x.mean()

    view_state = pdk.ViewState(latitude=centro_lat, longitude=centro_lon, zoom=11)

    deck = pdk.Deck(
        layers=[layer_rede, layer_pontos],
        initial_view_state=view_state,
        map_style="road",
        tooltip=False,
    )
    return deck, amostrado


# ----------------------------------------------------------------------
# Interface
# ----------------------------------------------------------------------
st.title("📍 Cobertura de Rede de Esgoto — Buffer 15m")
st.caption(
    "Cruza pontos CNEFE com a rede de esgoto (buffer de 15m). "
    "Calcula cobertura pela rede total e pela rede com tratamento (`Tratamento = Sim`)."
)

col1, col2 = st.columns(2)
with col1:
    arquivos_rede = st.file_uploader(
        "Arquivos de REDE de esgoto (.gpkg) — um por município",
        type=["gpkg"],
        accept_multiple_files=True,
        key="rede",
    )
with col2:
    arquivos_cnefe = st.file_uploader(
        "Arquivos CNEFE (.gpkg) — um por município",
        type=["gpkg"],
        accept_multiple_files=True,
        key="cnefe",
    )

st.divider()

if arquivos_rede and arquivos_cnefe:
    mapa_rede = {normalizar_nome(f.name): f for f in arquivos_rede}
    mapa_cnefe = {normalizar_nome(f.name): f for f in arquivos_cnefe}

    nomes_comuns = sorted(set(mapa_rede.keys()) & set(mapa_cnefe.keys()))
    nomes_sem_par_rede = sorted(set(mapa_rede.keys()) - set(mapa_cnefe.keys()))
    nomes_sem_par_cnefe = sorted(set(mapa_cnefe.keys()) - set(mapa_rede.keys()))

    if nomes_sem_par_rede or nomes_sem_par_cnefe:
        with st.expander("⚠️ Arquivos sem par correspondente (não serão processados)"):
            if nomes_sem_par_rede:
                st.write("Rede sem CNEFE correspondente:", nomes_sem_par_rede)
            if nomes_sem_par_cnefe:
                st.write("CNEFE sem rede correspondente:", nomes_sem_par_cnefe)

    if not nomes_comuns:
        st.error("Nenhum par rede/CNEFE encontrado. Verifique os nomes dos arquivos.")
    else:
        if st.button(f"▶️ Processar {len(nomes_comuns)} município(s)", type="primary"):
            resultados = []
            geodados = {}  # nome -> (cnefe_4326, rede_4326, col_trat)
            progresso = st.progress(0.0, text="Iniciando...")
            erros = []

            for i, nome in enumerate(nomes_comuns):
                progresso.progress((i) / len(nomes_comuns), text=f"Processando {nome.title()}...")
                try:
                    rede_file = mapa_rede[nome]
                    cnefe_file = mapa_cnefe[nome]
                    resultado, cnefe_4326, rede_4326 = processar_par(nome, rede_file.getvalue(), cnefe_file.getvalue())
                    resultados.append(resultado)
                    col_trat = encontrar_coluna_tratamento(rede_4326)
                    geodados[resultado["Município"]] = (cnefe_4326, rede_4326, col_trat)
                except Exception as e:
                    erros.append(f"{nome.title()}: {e}")

            progresso.progress(1.0, text="Concluído!")

            if erros:
                st.error("Erros ao processar alguns municípios:\n" + "\n".join(erros))

            if resultados:
                st.session_state["resultados_df"] = pd.DataFrame(resultados)
                st.session_state["geodados"] = geodados

    # Exibe resultados (persistem entre interações via session_state)
    if "resultados_df" in st.session_state:
        df = st.session_state["resultados_df"]
        geodados = st.session_state["geodados"]

        st.success(f"{len(df)} município(s) processado(s) com sucesso.")
        st.dataframe(df, use_container_width=True, hide_index=True)

        st.subheader("Totais consolidados")
        total_pontos = df["Pontos CNEFE (total)"].sum()
        total_cobertos = df["Cobertos - Rede Total"].sum()
        total_trat = df["Cobertos - Rede c/ Tratamento"].sum()
        cA, cB, cC = st.columns(3)
        cA.metric("Pontos CNEFE (total)", f"{total_pontos:,}".replace(",", "."))
        cB.metric(
            "Cobertos - Rede Total",
            f"{total_cobertos:,}".replace(",", "."),
            f"{100*total_cobertos/total_pontos:.2f}%",
        )
        cC.metric(
            "Cobertos - Rede c/ Tratamento",
            f"{total_trat:,}".replace(",", "."),
            f"{100*total_trat/total_pontos:.2f}%",
        )

        buffer_xlsx = io.BytesIO()
        with pd.ExcelWriter(buffer_xlsx, engine="openpyxl") as writer:
            df.to_excel(writer, index=False, sheet_name="Cobertura Esgoto")
        st.download_button(
            "⬇️ Baixar resultado em Excel",
            data=buffer_xlsx.getvalue(),
            file_name="cobertura_esgoto_por_municipio.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

        # -------------------- MAPA --------------------
        st.divider()
        st.subheader("🗺️ Visualização no mapa")

        municipio_selecionado = st.selectbox("Selecione o município para visualizar:", list(geodados.keys()))

        cnefe_4326, rede_4326, col_trat = geodados[municipio_selecionado]

        legenda_col1, legenda_col2, legenda_col3, legenda_col4, legenda_col5 = st.columns(5)
        legenda_col1.markdown("🟢 Coberto (rede c/ tratamento)")
        legenda_col2.markdown("🟠 Coberto (rede s/ tratamento)")
        legenda_col3.markdown("🔴 Não coberto")
        legenda_col4.markdown("🟩 Linha de rede tratada")
        legenda_col5.markdown("⬜ Linha de rede sem tratamento")

        with st.spinner("Montando mapa..."):
            deck, amostrado = montar_mapa(cnefe_4326, rede_4326, col_trat)
            if amostrado:
                st.caption(
                    f"⚠️ Exibindo amostra aleatória de {MAX_PONTOS_MAPA:,} pontos "
                    f"(de {len(cnefe_4326):,} totais) para manter o mapa fluido. "
                    "Os números da tabela acima usam o total completo.".replace(",", ".")
                )
            st.pydeck_chart(deck, use_container_width=True)

else:
    st.info("Envie os arquivos de rede e de CNEFE (podem ser vários municípios de uma vez) para iniciar.")

with st.expander("ℹ️ Como funciona o pareamento de arquivos"):
    st.markdown(
        """
        O app casa cada arquivo de **rede** com seu arquivo **CNEFE** pelo nome do município
        extraído do nome do arquivo (removendo prefixos como `NM_MUN_` / `CNEFE_`, acentos e underscores).

        Exemplo: `NM_MUN_São_Gonçalo.gpkg` ↔ `CNEFE_São_Gonçalo.gpkg` → pareados como **"são goncalo"**.

        Certifique-se de manter esse padrão de nomenclatura para todos os municípios.
        """
    )
