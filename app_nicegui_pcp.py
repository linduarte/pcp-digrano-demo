"""Aplicação NiceGUI para Planejamento e Controle de Produção (PCP) utilizando DuckDB e NiceGUI."""
import datetime
import json
import math
import os
import sys
from typing import Any, Callable, Optional

import duckdb
import pandas as pd
from nicegui import ui

# Garante que o diretório do script está no caminho de importação
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Tenta importar o módulo de sincronização do SCF
executar_sincronizacao: Optional[Callable[[], Any]]
try:
    from sincronizar_scf import executar_sincronizacao  # type: ignore[import-not-found]
except ImportError:
    executar_sincronizacao = None


# -----------------------------------------------------------------------------
# 1. CARREGADOR DE DADOS EM MEMÓRIA DUCKDB (NDJSON DO SCF / EXCEL FALLBACK)
# -----------------------------------------------------------------------------
def carregar_dados_duckdb():
    """Lê o ficheiro NDJSON sincronizado do SCF ou usa o Excel como fallback."""
    con = duckdb.connect(":memory:")
    ndjson_file = "fichas_tecnicas_scf.ndjson"
    excel_file = "Modelo_Ref_PCP_NDJSON.xlsx"
    if not os.path.exists(excel_file):
        excel_file = "Modelo_Modelo_Ref_PCP_NDJSON.xlsx"

    # Opção A: Ficheiro NDJSON nativo do SCF existe
    if os.path.exists(ndjson_file) and os.path.getsize(ndjson_file) > 0:
        con.execute(f"""
            CREATE TABLE fichas_tecnicas AS 
            SELECT * FROM read_ndjson_auto('{ndjson_file}')
        """)
        source_mode = "SCF NDJSON (SQL Server)"
    # Opção B: Fallback para a planilha Excel
    elif os.path.exists(excel_file):
        df_produtos = pd.read_excel(excel_file, sheet_name="PRODUTOS")
        df_fichas = pd.read_excel(excel_file, sheet_name="FICHA_TECNICA")

        con.register("df_produtos", df_produtos)
        con.register("df_fichas", df_fichas)

        con.execute("""
            CREATE TABLE fichas_tecnicas AS
            SELECT 
                CAST(p.Codigo_Caixa AS VARCHAR) AS codigo_caixa,
                p.Descricao_Caixa AS descricao_caixa,
                p.Linha AS linha,
                p.Pct_Por_Cx AS pct_por_cx,
                p.Uni_Por_Pct AS uni_por_pct,
                p.Qtd_Por_Tabuleiro AS qtd_por_tabuleiro,
                list({
                    'tipo': f.Tipo_Componente,
                    'codigo_insumo': CAST(f.Codigo_Insumo AS VARCHAR),
                    'descricao_insumo': f.Descricao_Insumo,
                    'peso_unid_kg': f.Peso_Unid_KG,
                    'peso_lote_receita_kg': f.Peso_Lote_Receita_KG,
                    'permite_meio_lote': f.Permite_Meio_Lote
                }) AS composicoes
            FROM df_produtos p
            JOIN df_fichas f ON p.Codigo_Caixa = f.Codigo_Produto
            GROUP BY ALL
        """)
        source_mode = "Excel Fallback"
    else:
        raise FileNotFoundError(
            "Nenhuma fonte de dados (NDJSON ou Excel) foi encontrada!"
        )

    return con, source_mode


# Inicialização global do DuckDB
estado_dados = dict(zip(("con_duck", "fonte_atual"), carregar_dados_duckdb()))


def consultar_produtos():
    """Return the product records ordered by box code."""
    return estado_dados["con_duck"].execute("""
        SELECT CAST(codigo_caixa AS VARCHAR) AS codigo_caixa, descricao_caixa, linha, pct_por_cx, uni_por_pct 
        FROM fichas_tecnicas 
        ORDER BY codigo_caixa
    """).df()


def calcular_ordem_duckdb(itens_op):
    """Return the ingredient breakdown for each production item."""
    if not itens_op:
        return []

    def _consultar_composicoes(codigo_caixa):
        query = """
            SELECT
                CAST(codigo_caixa AS VARCHAR) AS codigo_caixa,
                descricao_caixa,
                linha,
                pct_por_cx,
                uni_por_pct,
                comp.tipo AS tipo_comp,
                CAST(comp.codigo_insumo AS VARCHAR) AS cod_insumo,
                comp.descricao_insumo AS desc_insumo,
                COALESCE(comp.peso_unid_kg, 0) AS peso_unid_kg,
                COALESCE(comp.peso_lote_receita_kg, 1.0) AS peso_lote_receita_kg
            FROM fichas_tecnicas,
            UNNEST(composicoes) AS t(comp)
            WHERE CAST(codigo_caixa AS VARCHAR) = ?
        """
        return estado_dados["con_duck"].execute(query, [codigo_caixa]).df()

    resultados = []
    for item in itens_op:
        codigo_caixa = str(item["codigo_caixa"])
        caixas = float(item.get("caixas") or 0)
        pacotes = float(item.get("pacotes") or 0)
        unidades = float(item.get("unidades") or 0)

        if caixas == 0 and pacotes == 0 and unidades == 0:
            continue

        df_comp = _consultar_composicoes(codigo_caixa)
        if df_comp.empty:
            continue

        pct_cx = float(df_comp["pct_por_cx"].iloc[0] or 1)
        uni_pct = float(df_comp["uni_por_pct"].iloc[0] or 1)
        total_unidades = (caixas * pct_cx * uni_pct) + (pacotes * uni_pct) + unidades

        for _, row in df_comp.iterrows():
            peso_unid_kg = float(row["peso_unid_kg"] or 0)
            kg_liq = total_unidades * peso_unid_kg
            lote_kg = float(row["peso_lote_receita_kg"] or 1.0)
            if lote_kg <= 0:
                lote_kg = 1.0
            num_lotes = math.ceil((kg_liq / lote_kg) * 2) / 2

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
                    "kg_bruto": f"{num_lotes * lote_kg:.3f} KG",
                }
            )

    return resultados


# -----------------------------------------------------------------------------
# PASTA DE HISTÓRICO DE OPs
# -----------------------------------------------------------------------------
OP_FOLDER = "ordens_producao_scf"
os.makedirs(OP_FOLDER, exist_ok=True)


def carregar_historico_ops():
    """Carrega e retorna o histórico das ordens de produção salvas em JSON."""
    historico = []
    if not os.path.exists(OP_FOLDER):
        return historico
    for filename in sorted(os.listdir(OP_FOLDER), reverse=True):
        if filename.endswith(".json"):
            filepath = os.path.join(OP_FOLDER, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    historico.append(
                        {
                            "id": data.get("op_id"),
                            "data_hora": data.get("data_hora"),
                            "qtd_produtos": len(data.get("programacao_produtos", [])),
                            "qtd_insumos": len(data.get("explosao_insumos", [])),
                            "filename": filename,
                            "raw_json": data,
                        }
                    )
            except OSError, json.JSONDecodeError:
                pass
    return historico


# -----------------------------------------------------------------------------
# 2. INTERFACE GRÁFICA NICEGUI COM SINCRONIZAÇÃO
# -----------------------------------------------------------------------------
@ui.page("/")
# pylint: disable=too-many-locals,too-many-statements
def main_page():
    """Render the production-order interface and its history."""

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
                    "Motor de Cálculo de Receitas & Mapeamento SCF (DuckDB + NDJSON)"
                ).classes("text-xs opacity-80")

        with ui.row().classes("items-center gap-3"):
            badge_fonte = ui.badge(
                f"Fonte: {estado_dados['fonte_atual']}", color="teal"
            ).classes(
                "text-xs px-3 py-1 font-mono"
            )

            def acao_sincronizar_scf():
                if executar_sincronizacao is None:
                    ui.notify(
                        'Módulo "sincronizar_scf.py" não encontrado!', type="negative"
                    )
                    return

                try:
                    ui.notify("Conectando ao SQL Server do SCF...", type="info")
                    executar_sincronizacao()
                    estado_dados["con_duck"], estado_dados["fonte_atual"] = (
                        carregar_dados_duckdb()
                    )
                    badge_fonte.text = f"Fonte: {estado_dados['fonte_atual']}"

                    # Atualiza opções do dropdown de produtos
                    prods = consultar_produtos()
                    select_prod.options = {
                        str(
                            r["codigo_caixa"]
                        ): f"{r['codigo_caixa']} - {r['descricao_caixa']}"
                        for _, r in prods.iterrows()
                    }
                    select_prod.update()

                    ui.notify(
                        "Sucesso! Base de Fichas Técnicas sincronizada com o SCF!",
                        type="positive",
                        icon="sync",
                    )
                except (duckdb.Error, OSError, ValueError, RuntimeError) as e:
                    ui.notify(f"Erro na sincronização: {e}", type="negative")

            ui.button("🔄 Sincronizar SCF", on_click=acao_sincronizar_scf).classes(
                "bg-secondary text-white text-xs"
            )

    produtos_df = consultar_produtos()
    dict_produtos = {
        str(row["codigo_caixa"]): f"{row['codigo_caixa']} - {row['descricao_caixa']}"
        for _, row in produtos_df.iterrows()
    }

    ordem_itens = []

    with ui.tabs().classes("w-full bg-slate-100 text-slate-700 font-bold") as tabs:
        tab_lançamento = ui.tab(
            "Gerador de OP / Explosão Insumos", icon="add_shopping_cart"
        )
        tab_historico = ui.tab(
            "Histórico de OPs Enviadas ao SCF", icon="format_list_bulleted"
        )

    with ui.tab_panels(tabs, value=tab_lançamento).classes("w-full bg-slate-50 p-6"):
        # ---------------------------------------------------------------------
        # ABA 1: GERADOR DE OP
        # ---------------------------------------------------------------------
        with ui.tab_panel(tab_lançamento).classes("gap-6"):
            # Card 1: Inserção de Ordens
            with ui.card().classes(
                "w-full p-5 border border-slate-200 shadow-sm rounded-xl bg-white mb-6"
            ):
                ui.label(
                    "1. Lançamento da Ordem de Produção (Intenção PCP Multi-Produto)"
                ).classes("text-base font-bold text-slate-800 mb-3")

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
                            ui.notify(
                                "Informe ao menos uma quantidade!", type="warning"
                            )
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
                            f"Item {cod} adicionado à Ordem de Produção!",
                            type="positive",
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

                    with ui.row().classes("gap-3"):

                        def limpar_tudo():
                            ordem_itens.clear()
                            atualizar_tabela_insumos()
                            ui.notify("Ordem de Produção limpa.", type="info")

                        def confirmar_e_enviar_scf():
                            if not ordem_itens:
                                ui.notify(
                                    "Nenhum item na Ordem de Produção para enviar!",
                                    type="warning",
                                )
                                return

                            insumos_calc = calcular_ordem_duckdb(ordem_itens)
                            now_str = datetime.datetime.now().strftime(
                                "%Y-%m-%d %H:%M:%S"
                            )
                            op_id = f"OP-{datetime.datetime.now().strftime('%Y%m%d-%H%M%S')}"

                            payload_op = {
                                "op_id": op_id,
                                "data_hora": now_str,
                                "linha_producao": "Linha DiGrano",
                                "programacao_produtos": ordem_itens,
                                "explosao_insumos": insumos_calc,
                            }

                            filename = f"{op_id}.json"
                            filepath = os.path.join(OP_FOLDER, filename)
                            with open(filepath, "w", encoding="utf-8") as f:
                                json.dump(payload_op, f, indent=2, ensure_ascii=False)

                            ordem_itens.clear()
                            atualizar_tabela_insumos()
                            atualizar_historico_ui()
                            ui.notify(
                                f"Sucesso! {op_id} confirmada e salva para o SCF!",
                                type="positive",
                                icon="send",
                            )

                        ui.button(
                            "Limpar Ordem", icon="delete_sweep", on_click=limpar_tudo
                        ).props("flat color=red")
                        ui.button(
                            "Confirmar & Enviar para SCF (JSON)",
                            icon="send",
                            on_click=confirmar_e_enviar_scf,
                        ).classes("bg-primary text-white shadow-md")

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

        # ---------------------------------------------------------------------
        # ABA 2: HISTÓRICO E CONSULTA DE OPs DO SCF
        # ---------------------------------------------------------------------
        with ui.tab_panel(tab_historico):
            with ui.card().classes(
                "w-full p-5 border border-slate-200 shadow-sm rounded-xl bg-white"
            ):
                ui.label("Histórico de Ordens de Produção Confirmadas").classes(
                    "text-base font-bold text-slate-800 mb-2"
                )
                ui.label(
                    "Aqui o PCP e o Chão de Fábrica (SCF) consultam todas as OPs geradas e salvas em JSON."
                ).classes("text-xs text-slate-500 mb-4")

                container_historico = ui.column().classes("w-full gap-4")

                def visualizar_json_dialog(raw_data):
                    with (
                        ui.dialog() as dialog,
                        ui.card().classes("w-full max-w-3xl p-6"),
                    ):
                        ui.label(f"Payload JSON da {raw_data.get('op_id')}").classes(
                            "text-lg font-bold text-slate-800 mb-2"
                        )
                        ui.code(
                            json.dumps(raw_data, indent=2, ensure_ascii=False),
                            language="json",
                        ).classes(
                            "w-full max-h-96 overflow-y-auto bg-slate-900 text-green-400 p-4 rounded-lg font-mono text-xs"
                        )
                        ui.button("Fechar", on_click=dialog.close).classes(
                            "mt-4 bg-slate-700 text-white"
                        )
                    dialog.open()

                def atualizar_historico_ui():
                    container_historico.clear()
                    dados_hist = carregar_historico_ops()
                    if not dados_hist:
                        with container_historico:
                            ui.label(
                                "Nenhuma Ordem de Produção salva até o momento."
                            ).classes("text-slate-400 italic text-sm p-4")
                        return

                    for op in dados_hist:
                        with container_historico:
                            with ui.card().classes(
                                "w-full p-4 border border-slate-200 rounded-lg bg-slate-50 flex-row items-center justify-between"
                            ):
                                with ui.row().classes("items-center gap-6"):
                                    ui.badge(op["id"], color="primary").classes(
                                        "text-sm px-3 py-1 font-mono"
                                    )
                                    ui.label(f"Data: {op['data_hora']}").classes(
                                        "text-sm text-slate-600"
                                    )
                                    ui.label(
                                        f"Produtos: {op['qtd_produtos']} | Insumos Explosão: {op['qtd_insumos']}"
                                    ).classes("text-sm font-semibold text-slate-800")

                                raw = op["raw_json"]
                                ui.button(
                                    "Ver JSON do SCF",
                                    icon="code",
                                    on_click=lambda _, r=raw: visualizar_json_dialog(r),
                                ).classes("bg-secondary text-white text-xs")

                atualizar_historico_ui()


ui.run(title="PCP DiGrano - NiceGUI & DuckDB", port=8085, reload=False)
