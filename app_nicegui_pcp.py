"""Aplicação NiceGUI para cálculo de ordens de produção com dados carregados em memória no DuckDB."""

import math

import duckdb
import pandas as pd
from nicegui import ui


# -----------------------------------------------------------------------------
# 1. CARREGADOR DE DADOS EM MEMÓRIA DUCKDB (SIMULANDO NDJSON)
# -----------------------------------------------------------------------------
def carregar_dados_ndjson_duckdb():
    """Lê o ficheiro Excel fornecido e cria a tabela aninhada em memória no DuckDB."""
    # Na linha 11 do app_nicegui_pcp.py:
    excel_file = "Modelo_Ref_PCP_NDJSON.xlsx"

    df_produtos = pd.read_excel(excel_file, sheet_name="PRODUTOS")
    df_fichas = pd.read_excel(excel_file, sheet_name="FICHA_TECNICA")

    con = duckdb.connect(":memory:")
    con.register("df_produtos", df_produtos)
    con.register("df_fichas", df_fichas)

    # Criação da estrutura aninhada (NDJSON)
    con.execute("""
        CREATE TABLE fichas_tecnicas AS
        SELECT 
            p.Codigo_Caixa AS codigo_caixa,
            p.Descricao_Caixa AS descricao_caixa,
            p.Linha AS linha,
            p.Pct_Por_Cx AS pct_por_cx,
            p.Uni_Por_Pct AS uni_por_pct,
            p.Qtd_Por_Tabuleiro AS qtd_por_tabuleiro,
            list({
                'tipo': f.Tipo_Componente,
                'codigo_insumo': f.Codigo_Insumo,
                'descricao_insumo': f.Descricao_Insumo,
                'peso_unid_kg': f.Peso_Unid_KG,
                'peso_lote_receita_kg': f.Peso_Lote_Receita_KG,
                'permite_meio_lote': f.Permite_Meio_Lote
            }) AS composicoes
        FROM df_produtos p
        JOIN df_fichas f ON p.Codigo_Caixa = f.Codigo_Produto
        GROUP BY ALL
    """)

    return con


con_duck = carregar_dados_ndjson_duckdb()


def consultar_produtos():
    """Return the products available in the technical sheets."""
    return con_duck.execute("""
        SELECT codigo_caixa, descricao_caixa, linha, pct_por_cx, uni_por_pct 
        FROM fichas_tecnicas 
        ORDER BY codigo_caixa
    """).df()


def calcular_ordem_duckdb(itens_op):
    """Calculate ingredient quantities for the requested production order."""
    if not itens_op:
        return []

    resultados = []
    for item in itens_op:
        cod = str(item["codigo_caixa"])
        cx = float(item.get("caixas") or 0)
        pct = float(item.get("pacotes") or 0)
        und = float(item.get("unidades") or 0)

        if cx == 0 and pct == 0 and und == 0:
            continue

        query = f"""
            SELECT 
                codigo_caixa,
                descricao_caixa,
                linha,
                pct_por_cx,
                uni_por_pct,
                comp.tipo AS tipo_comp,
                comp.codigo_insumo AS cod_insumo,
                comp.descricao_insumo AS desc_insumo,
                comp.peso_unid_kg,
                comp.peso_lote_receita_kg,
                comp.permite_meio_lote
            FROM fichas_tecnicas,
            UNNEST(composicoes) AS t(comp)
            WHERE CAST(codigo_caixa AS VARCHAR) = '{cod}'
        """

        df_comp = con_duck.execute(query).df()
        if df_comp.empty:
            continue

        pct_cx = df_comp["pct_por_cx"].iloc[0]
        uni_pct = df_comp["uni_por_pct"].iloc[0]

        total_unidades = (cx * pct_cx * uni_pct) + (pct * uni_pct) + und
        resultados.extend(_calcular_composicoes(df_comp, total_unidades))

    return resultados


def _calcular_composicoes(df_comp, total_unidades):
    """Build rounded batch results for each ingredient composition."""
    resultados = []
    for _, row in df_comp.iterrows():
        kg_liq = total_unidades * row["peso_unid_kg"]
        lote_kg = row["peso_lote_receita_kg"]
        receitas_exatas = kg_liq / lote_kg

        # Regra de arredondamento em passos de 0,5
        num_lotes = math.ceil(receitas_exatas * 2) / 2
        kg_bruto = num_lotes * lote_kg
        resultados.append(
            {
                "codigo_caixa": str(row["codigo_caixa"]),
                "descricao_caixa": row["descricao_caixa"],
                "total_unidades": f"{total_unidades:,.0f}",
                "cod_insumo": str(row["cod_insumo"]),
                "desc_insumo": row["desc_insumo"],
                "tipo_comp": row["tipo_comp"],
                "kg_liquido": f"{kg_liq:.3f} KG",
                "lote_kg": f"{lote_kg:.2f} KG",
                "num_lotes": f"{num_lotes:.1f}",
                "kg_bruto": f"{kg_bruto:.3f} KG",
            }
        )
    return resultados


# -----------------------------------------------------------------------------
# 2. INTERFACE GRÁFICA NICEGUI
# -----------------------------------------------------------------------------
@ui.page("/")
def main_page():
    """Render the PCP dashboard page for recipe calculations."""
    ui.colors(primary="#1E40AF", secondary="#0D9488", accent="#F59E0B", dark="#0F172A")

    with ui.header().classes(
        "bg-primary text-white p-4 items-center justify-between shadow-lg"
    ):
        with ui.row().classes("items-center gap-3"):
            ui.icon("factory", size="32px")
            with ui.column().classes("gap-0"):
                ui.label("PCP - Linha de Alimentos DiGrano").classes(
                    "text-xl font-bold tracking-wide"
                )
                ui.label(
                    "Motor de Cálculo de Receitas em Tempo Real (DuckDB + NDJSON)"
                ).classes("text-xs opacity-80")
        ui.badge("NDJSON Mode Active", color="teal").classes(
            "text-xs px-3 py-1 font-mono"
        )

    produtos_df = consultar_produtos()
    dict_produtos = {
        str(row["codigo_caixa"]): f"{row['codigo_caixa']} - {row['descricao_caixa']}"
        for _, row in produtos_df.iterrows()
    }

    ordem_itens = []

    with ui.column().classes("w-full p-6 gap-6 bg-slate-50"):
        # Card 1: Inserção de Ordens
        with ui.card().classes(
            "w-full p-5 border border-slate-200 shadow-sm rounded-xl bg-white"
        ):
            ui.label("1. Lançamento da Ordem de Produção (Intenção PCP)").classes(
                "text-base font-bold text-slate-800 mb-3"
            )

            with ui.row().classes("w-full items-center gap-4 flex-wrap"):
                select_prod = ui.select(
                    options=dict_produtos,
                    label="Selecione o Produto Final",
                    value=list(dict_produtos.keys())[0] if dict_produtos else None,
                ).classes("w-96")

                input_cx = ui.number(
                    label="Caixas (CX)", value=0, min=0, format="%.0f"
                ).classes("w-32")
                input_pct = ui.number(
                    label="Pacotes (PCT)", value=0, min=0, format="%.0f"
                ).classes("w-32")
                input_und = ui.number(
                    label="Unidades (UNI)", value=0, min=0, format="%.0f"
                ).classes("w-32")

                def adicionar_item_op():
                    cod = select_prod.value
                    cx = input_cx.value or 0
                    pct = input_pct.value or 0
                    und = input_und.value or 0

                    if cx == 0 and pct == 0 and und == 0:
                        ui.notify("Informe ao menos uma quantidade!", type="warning")
                        return

                    ordem_itens.append(
                        {
                            "codigo_caixa": cod,
                            "caixas": cx,
                            "pacotes": pct,
                            "unidades": und,
                        }
                    )
                    atualizar_tabela_insumos()
                    ui.notify(
                        f"Item {cod} adicionado à Ordem de Produção!", type="positive"
                    )

                ui.button(
                    "Adicionar Lote", icon="add_circle", on_click=adicionar_item_op
                ).classes("bg-secondary text-white shadow-md")

        # Card 2: Tabela de Resultados
        with ui.card().classes(
            "w-full p-5 border border-slate-200 shadow-sm rounded-xl bg-white"
        ):
            with ui.row().classes("w-full items-center justify-between mb-3"):
                ui.label("2. Explosão Consolidada de Insumos & Receitas").classes(
                    "text-base font-bold text-slate-800"
                )

                def limpar_tudo():
                    ordem_itens.clear()
                    atualizar_tabela_insumos()
                    ui.notify("Ordem de Produção limpa.", type="info")

                ui.button(
                    "Limpar Ordem", icon="delete_sweep", on_click=limpar_tudo
                ).props("flat color=red")

            colunas_tabela = [
                {
                    "name": "codigo_caixa",
                    "label": "Cód. Prod.",
                    "field": "codigo_caixa",
                    "align": "left",
                },
                {
                    "name": "descricao_caixa",
                    "label": "Produto Final",
                    "field": "descricao_caixa",
                    "align": "left",
                },
                {
                    "name": "total_unidades",
                    "label": "Total Unid.",
                    "field": "total_unidades",
                    "align": "center",
                },
                {
                    "name": "tipo_comp",
                    "label": "Tipo",
                    "field": "tipo_comp",
                    "align": "center",
                },
                {
                    "name": "cod_insumo",
                    "label": "Cód. Insumo",
                    "field": "cod_insumo",
                    "align": "left",
                },
                {
                    "name": "desc_insumo",
                    "label": "Componente / Receita Semiacabado",
                    "field": "desc_insumo",
                    "align": "left",
                },
                {
                    "name": "kg_liquido",
                    "label": "Nec. Líquida (KG)",
                    "field": "kg_liquido",
                    "align": "right",
                },
                {
                    "name": "lote_kg",
                    "label": "Lote Padrão",
                    "field": "lote_kg",
                    "align": "right",
                },
                {
                    "name": "num_lotes",
                    "label": "Nº Receitas (0.5)",
                    "field": "num_lotes",
                    "align": "center",
                },
                {
                    "name": "kg_bruto",
                    "label": "Total Bruto a Preparar",
                    "field": "kg_bruto",
                    "align": "right",
                },
            ]

            tabela = ui.table(
                columns=colunas_tabela, rows=[], row_key="cod_insumo"
            ).classes("w-full shadow-none border border-slate-200 rounded-lg")

            def atualizar_tabela_insumos():
                dados = calcular_ordem_duckdb(ordem_itens)
                tabela.rows = dados
                tabela.update()


# Executa o NiceGUI na porta 8080
ui.run(title="PCP DiGrano - NiceGUI & DuckDB", port=8085, reload=False)
