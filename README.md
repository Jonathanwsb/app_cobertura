# Cobertura de Rede de Esgoto — Buffer 15m

App Streamlit que cruza pontos CNEFE com a rede de esgoto (buffer de 15m) e calcula
a cobertura, tanto pela rede total quanto pela rede com tratamento (`Tratamento = Sim`).

## Rodar localmente

```bash
pip install -r requirements.txt
python -m streamlit run app.py
```

## Como usar

1. Suba os arquivos `.gpkg` de **rede** (um ou vários municípios).
2. Suba os arquivos `.gpkg` de **CNEFE** correspondentes.
3. O app pareia automaticamente pelo nome do município no arquivo
   (ex: `NM_MUN_São_Gonçalo.gpkg` ↔ `CNEFE_São_Gonçalo.gpkg`).
4. Clique em "Processar" e baixe o resultado em Excel.

## Deploy no Streamlit Cloud

1. Crie um repositório no GitHub e suba estes arquivos (`app.py`, `requirements.txt`):

```bash
git init
git add app.py requirements.txt README.md
git commit -m "App cobertura de esgoto - buffer 15m"
git branch -M main
git remote add origin https://github.com/Jonathanwsb/NOME_DO_REPO.git
git push -u origin main
```

2. Acesse [share.streamlit.io](https://share.streamlit.io), conecte o repositório e
   aponte para `app.py`.

## Observações

- A coluna de tratamento esperada na camada de rede é `Tratamento`, com valor `Sim`
  para segmentos tratados (ajustável em `TREAT_COL_CANDIDATES` no `app.py`).
- O CRS do CNEFE é reprojetado automaticamente para o CRS da rede (deve ser um
  CRS métrico, ex: EPSG:31983) antes do cálculo do buffer.
- Arquivos grandes (CNEFE com centenas de milhares de pontos) podem levar alguns
  segundos por município — normal.
