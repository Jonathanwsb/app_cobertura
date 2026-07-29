import io
import re
import unicodedata

import geopandas as gpd
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Cobertura de Esgoto - Buffer 15m", layout="wide")

BUFFER_M = 15
TREAT_COL_CANDIDATES = ["Tratamento", "TRATAMENTO", "tratamento"]
TREAT_VALUE = "Sim"


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
    """Processa um par (rede, cnefe) e retorna um dicionário com os resultados."""
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
            qtd_trat = 0
    else:
        qtd_trat = None  # coluna não encontrada

    return {
        "Município": nome_municipio.title(),
        "Pontos CNEFE (total)": total_pontos,
        "Cobertos - Rede Total": qtd_total,
        "% Rede Total": round(100 * qtd_total / total_pontos, 2) if total_pontos else 0,
        "Cobertos - Rede c/ Tratamento": qtd_trat,
        "% Rede c/ Tratamento": round(100 * qtd_trat / total_pontos, 2) if (total_pontos and qtd_trat is not None) else None,
        "Segmentos de Rede": len(rede),
        "Coluna Tratamento encontrada": col_trat if col_trat else "NÃO ENCONTRADA",
    }


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
    # Pareia os arquivos pelo nome normalizado do município
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
            progresso = st.progress(0.0, text="Iniciando...")
            erros = []

            for i, nome in enumerate(nomes_comuns):
                progresso.progress((i) / len(nomes_comuns), text=f"Processando {nome.title()}...")
                try:
                    rede_file = mapa_rede[nome]
                    cnefe_file = mapa_cnefe[nome]
                    resultado = processar_par(nome, rede_file.getvalue(), cnefe_file.getvalue())
                    resultados.append(resultado)
                except Exception as e:
                    erros.append(f"{nome.title()}: {e}")

            progresso.progress(1.0, text="Concluído!")

            if erros:
                st.error("Erros ao processar alguns municípios:\n" + "\n".join(erros))

            if resultados:
                df = pd.DataFrame(resultados)
                st.success(f"{len(resultados)} município(s) processado(s) com sucesso.")
                st.dataframe(df, use_container_width=True, hide_index=True)

                # Totais consolidados
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

                # Download Excel
                buffer_xlsx = io.BytesIO()
                with pd.ExcelWriter(buffer_xlsx, engine="openpyxl") as writer:
                    df.to_excel(writer, index=False, sheet_name="Cobertura Esgoto")
                st.download_button(
                    "⬇️ Baixar resultado em Excel",
                    data=buffer_xlsx.getvalue(),
                    file_name="cobertura_esgoto_por_municipio.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
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
