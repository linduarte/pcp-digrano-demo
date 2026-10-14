"""
app_nicegui_pcp.py
Aplicação de Interface do PCP em NiceGUI integrada ao DuckDB e NDJSON.
Trata formatação PT-BR para exibição, agrupamento único de insumos,
arredondamento 0.5 e exibe a memória de cálculo das unidades físicas de produção.
"""

import datetime
import json
import math
import os
import re
import sys
from typing import Any, Callable, Optional, Tuple

import duckdb
import pandas as pd
from nicegui import ui

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

try:
    _utils_formatacao = __import__("utils_formatacao")
    _converter_para_float_impl = _utils_formatacao.converter_para_float
    _formatar_para_scf_impl = _utils_formatacao.formatar_para_scf
except ImportError, AttributeError:

    def _formatar_para_scf_fallback(valor: Any, casas_decimais: int = 3) -> str:
        if valor is None:
            return "0,000"
        try:
            val_f = float(valor)
            txt = f"{val_f:,.{casas_decimais}f}"
            return txt.replace(",", "X").replace(".", ",").replace("X", ".")
        except ValueError, TypeError:
            return str(valor)

    def _converter_para_float_fallback(valor_raw: Any) -> float:
        if not valor_raw:
            return 0.0
        if isinstance(valor_raw, (int, float)):
            return float(valor_raw)
        try:
            texto = str(valor_raw).strip().replace(".", "").replace(",", ".")
            return float(texto)
        except ValueError:
            return 0.0

    _formatar_para_scf_impl = _formatar_para_scf_fallback
    _converter_para_float_impl = _converter_para_float_fallback


def formatar_para_scf(valor: Any, casas_decimais: int = 3) -> str:
    """Formata um valor para o padrão de moeda SCF."""
    return _formatar_para_scf_impl(valor, casas_decimais)


def converter_para_float(valor: Any) -> float:
    """Converte valores em texto, numéricos ou de moeda para float."""
    return _converter_para_float_impl(valor)


executar_sincronizacao: Optional[Callable[[], Any]] = None

for _nome_modulo_scf in ("sincronizar_scf", "src.sincronizar_scf"):
    try:
        _modulo_scf = __import__(_nome_modulo_scf, fromlist=["executar_sincronizacao"])
        executar_sincronizacao = getattr(_modulo_scf, "executar_sincronizacao", None)
        if executar_sincronizacao is not None:
            break
    except ImportError:
        continue

if executar_sincronizacao is None:
    try:
        from sincronizar_scf import executar_sincronizacao  # type: ignore[import-not-found]
    except ImportError:
        executar_sincronizacao = None


# -----------------------------------------------------------------------------
# FUNÇÕES AUXILIARES DE EMBALAGEM E MEMÓRIA DE CÁLCULO
# -----------------------------------------------------------------------------
def gerar_memoria_calculo_unidades(
    cx: float, pct: float, und: float, pct_por_cx: float, uni_por_pct: float
) -> str:
    """
    Gera a memória de cálculo visual tratada inclusive para entradas puras em unidades (0 CX, 0 PCT, X UN).
    """
    qtd_cx_und = cx * pct_por_cx * uni_por_pct
    qtd_pct_und = pct * uni_por_pct
    total_unidades = qtd_cx_und + qtd_pct_und + und

    partes = []
    partes_soma = []

    if cx > 0:
        partes.append(f"({int(cx)} CX × {int(pct_por_cx)} PCT × {int(uni_por_pct)} UN)")
        partes_soma.append(f"{int(qtd_cx_und):,}".replace(",", "."))

    if pct > 0:
        partes.append(f"({int(pct)} PCT × {int(uni_por_pct)} UN)")
        partes_soma.append(f"{int(qtd_pct_und):,}".replace(",", "."))

    if und > 0:
        partes.append(f"{int(und)} UN")
        partes_soma.append(f"{int(und):,}".replace(",", "."))

    if not partes:
        return "0 Unidades"

    formula_str = " + ".join(partes)
    soma_str = " + ".join(partes_soma)

    if len(partes) > 1:
        return f"{formula_str} = {soma_str} = {int(total_unidades):,} Unidades".replace(
            ",", "."
        )
    else:
        return f"{formula_str} = {int(total_unidades):,} Unidades".replace(",", ".")


def obter_fatores_embalagem(
    codigo_caixa: str, descricao_caixa: str
) -> Tuple[float, float]:
    """Retorna os fatores exatos de embalagem para homologação conforme a planilha/BOM."""
    str_cod = str(codigo_caixa).strip()

    # Itens fabricados diretamente em unidades/massa sem caixa comercial
    if str_cod.upper().startswith("SCF"):
        return 1.0, 1.0

    # 1. Mapeamento explícito para os produtos homologados
    if "102254" in str_cod:
        return 4.0, 5.0  # Esfirra: 1 CX = 4 PCT, 1 PCT = 5 UN -> 1 CX = 20 UN
    if "101218" in str_cod:
        return 3.0, 10.0  # Cigarrete: 1 CX = 3 PCT, 1 PCT = 10 UN -> 1 CX = 30 UN

    # 2. Parsing de padrões via descrição comercial
    desc_upper = str(descricao_caixa).upper()
    match_pct = re.search(r"CX\s*C/\s*(\d+)\s*PCT", desc_upper)
    if match_pct:
        pct = float(match_pct.group(1))
        uni = 5.0 if pct == 4.0 else 10.0
        return pct, uni

    match_cx = re.search(r"CX\s*C/\s*(\d+)", desc_upper) or re.search(
        r"CX\s*(\d+)", desc_upper
    )
    if match_cx:
        try:
            total_un = int(match_cx.group(1))
            if total_un == 30:
                return 3.0, 10.0
            if total_un == 40:
                return 4.0, 10.0
            if total_un == 20:
                return 4.0, 5.0
        except ValueError:
            pass

    return 3.0, 10.0


# -----------------------------------------------------------------------------
# CARREGADOR DE DADOS DUCKDB
# -----------------------------------------------------------------------------
def carregar_dados_duckdb():
    """Carrega os dados de fichas técnicas em memória usando DuckDB."""
    con = duckdb.connect(database=":memory:")
    con.execute("DROP TABLE IF EXISTS fichas_tecnicas;")

    ndjson_file = "fichas_tecnicas_scf.ndjson"
    excel_file = "Modelo_Ref_PCP_NDJSON.xlsx"
    if not os.path.exists(excel_file):
        excel_file = "Modelo_Modelo_Ref_PCP_NDJSON.xlsx"

    if os.path.exists(ndjson_file) and os.path.getsize(ndjson_file) > 0:
        con.execute(f"""
            CREATE TABLE fichas_tecnicas AS 
            SELECT * FROM read_ndjson_auto('{ndjson_file}')
        """)
        source_mode = "SCF NDJSON (SQL Server)"
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
                    'permite_meio_lote': f.Permite_Meio_Lote,
                    'unidade': 'KG'
                }) AS composicoes
            FROM df_produtos p
            JOIN df_fichas f ON p.Codigo_Caixa = f.Codigo_Produto
            GROUP BY ALL
        """)
        source_mode = "Excel Fallback"
    else:
        raise FileNotFoundError("Nenhuma fonte de dados encontrada!")

    return con, source_mode


estado_dados = dict(zip(("con_duck", "fonte_atual"), carregar_dados_duckdb()))


def consultar_produtos():
    """Retorna a lista de produtos cadastrados em ordem de código."""
    return (
        estado_dados["con_duck"]
        .execute("""
        SELECT CAST(codigo_caixa AS VARCHAR) AS codigo_caixa, descricao_caixa, linha, pct_por_cx, uni_por_pct 
        FROM fichas_tecnicas 
        ORDER BY codigo_caixa
    """)
        .df()
    )


def calcular_ordem_duckdb(itens_op):
    """Calcula a necessidade de insumos para a ordem de produção com base no DuckDB com regra fixa imutável."""
    if not itens_op:
        return []

    def _consultar_composicoes(codigo_caixa: str):
        raw_str = str(codigo_caixa or "").strip()
        cod_limpo = raw_str.split("-")[0].strip() if "-" in raw_str else raw_str

        if cod_limpo.upper().startswith("SCF"):
            query_scf = """
                SELECT
                    TRIM(CAST(codigo_caixa AS VARCHAR)) AS codigo_caixa,
                    descricao_caixa,
                    linha,
                    pct_por_cx,
                    uni_por_pct,
                    comp.tipo AS tipo_comp,
                    TRIM(CAST(comp.codigo_insumo AS VARCHAR)) AS cod_insumo,
                    comp.descricao_insumo AS desc_insumo,
                    COALESCE(comp.peso_unid_kg, 0) AS peso_unid_kg,
                    COALESCE(comp.peso_lote_receita_kg, 1.0) AS peso_lote_receita_kg,
                    COALESCE(comp.unidade, 'KG') AS unidade
                FROM fichas_tecnicas,
                UNNEST(composicoes) AS t(comp)
                WHERE UPPER(TRIM(CAST(codigo_caixa AS VARCHAR))) = UPPER(?)
                   OR UPPER(TRIM(CAST(codigo_caixa AS VARCHAR))) LIKE UPPER(?)
            """
            try:
                df_scf = (
                    estado_dados["con_duck"]
                    .execute(query_scf, [cod_limpo, f"%{cod_limpo}%"])
                    .df()
                )
                if not df_scf.empty:
                    return df_scf
            except AttributeError, TypeError, ValueError, duckdb.Error:
                pass

        query_padrao = """
            SELECT
                TRIM(CAST(codigo_caixa AS VARCHAR)) AS codigo_caixa,
                descricao_caixa,
                linha,
                pct_por_cx,
                uni_por_pct,
                comp.tipo AS tipo_comp,
                TRIM(CAST(comp.codigo_insumo AS VARCHAR)) AS cod_insumo,
                comp.descricao_insumo AS desc_insumo,
                COALESCE(comp.peso_unid_kg, 0) AS peso_unid_kg,
                COALESCE(comp.peso_lote_receita_kg, 1.0) AS peso_lote_receita_kg,
                COALESCE(comp.unidade, 'KG') AS unidade
            FROM fichas_tecnicas,
            UNNEST(composicoes) AS t(comp)
            WHERE UPPER(TRIM(CAST(codigo_caixa AS VARCHAR))) = UPPER(?)
        """
        try:
            return estado_dados["con_duck"].execute(query_padrao, [cod_limpo]).df()
        except AttributeError, TypeError, ValueError, duckdb.Error:
            return pd.DataFrame()

    def _obter_total_unidades(item):
        raw_cod = str(item.get("codigo_caixa", "")).strip()
        codigo_caixa = (
            raw_cod.split("-", maxsplit=1)[0].strip() if "-" in raw_cod else raw_cod
        )

        caixas = float(item.get("caixas") or 0)
        pacotes = float(item.get("pacotes") or 0)
        unidades = float(item.get("unidades") or 0)

        if caixas == 0 and pacotes == 0 and unidades == 0:
            return None

        df_comp = _consultar_composicoes(codigo_caixa)
        if df_comp.empty:
            return None

        desc_prod = str(df_comp["descricao_caixa"].iloc[0] or "")
        pct_cx, uni_pct = obter_fatores_embalagem(codigo_caixa, desc_prod)

        if codigo_caixa.upper().startswith("SCF"):
            total_unidades = caixas + pacotes + unidades
            total_unidades_caixa = 1.0
        else:
            total_unidades = (
                (caixas * pct_cx * uni_pct) + (pacotes * uni_pct) + unidades
            )
            total_unidades_caixa = pct_cx * uni_pct

        return df_comp, total_unidades, total_unidades_caixa

    def _adicionar_insumo(
        insumos_map,
        row,
        total_unidades,
        total_unidades_caixa,
        cod_produto_origem: str = "",
    ):
        cod_insumo = str(row.get("cod_insumo", "") or "").strip()
        desc_insumo = str(row.get("desc_insumo", "") or "").strip()
        unidade = str(row.get("unidade", "KG") or "KG").strip()
        linha = str(row.get("linha", "ENCAIXOTAMENTO") or "ENCAIXOTAMENTO").strip()

        # Ignora registros que não são insumos de produção
        if not cod_insumo or cod_insumo.startswith("10") or desc_insumo == cod_insumo:
            return

        raw_peso = float(row.get("peso_unid_kg") or 0.0)

        # ---------------------------------------------------------------------
        # ARCABOUÇO FIXO DE TRATAMENTO DE PESO UNITÁRIO
        # Se o peso unitário cadastrado for superior ao peso de uma unidade física individual (> 0.20 KG),
        # significa que a base cadastrou o peso referente à caixa inteira.
        # Nesses casos dividimos por total_unidades_caixa. Para itens já unitários (ex: 0.075 KG da esfirra),
        # mantemos o peso unitário direto sem alterar!
        # ---------------------------------------------------------------------
        if total_unidades_caixa > 1 and raw_peso > 0.20:
            peso_unid_kg = raw_peso / total_unidades_caixa
        else:
            peso_unid_kg = raw_peso

        necess_liquida_item = total_unidades * peso_unid_kg
        lote_kg = float(row.get("peso_lote_receita_kg") or 1.0)

        if cod_insumo not in insumos_map:
            insumos_map[cod_insumo] = {
                "cod_insumo": cod_insumo,
                "desc_insumo": desc_insumo,
                "linha": linha,
                "unidade": unidade,
                "lote_kg": lote_kg,
                "necessidade_liquida_kg": 0.0,
                "produtos_origem": set(),
            }

        insumos_map[cod_insumo]["necessidade_liquida_kg"] += necess_liquida_item
        if cod_produto_origem:
            insumos_map[cod_insumo]["produtos_origem"].add(cod_produto_origem)

    def _montar_resultado(item):
        nec_liq = item["necessidade_liquida_kg"]
        lote_kg = item["lote_kg"]
        qtd_prods = len(item.get("produtos_origem", set()))
        foi_somado = qtd_prods > 1

        if lote_kg > 0 and item["unidade"] == "KG":
            receitas_exatas = nec_liq / lote_kg
            num_lotes = math.ceil(receitas_exatas * 2) / 2
            total_bruto = num_lotes * lote_kg
        else:
            num_lotes = 1.0
            total_bruto = nec_liq

        desc_exibida = (
            f"{item['desc_insumo']} (Soma de {qtd_prods} produtos)"
            if foi_somado
            else item["desc_insumo"]
        )

        return {
            "cod_insumo": item["cod_insumo"],
            "desc_insumo": desc_exibida,
            "linha": item["linha"],
            "lote_kg_str": formatar_para_scf(lote_kg, casas_decimais=3),
            "unidade": item["unidade"],
            "num_lotes": formatar_para_scf(num_lotes, casas_decimais=1),
            "total_bruto_str": formatar_para_scf(total_bruto, casas_decimais=3),
            "kg_liquido": formatar_para_scf(nec_liq, casas_decimais=3),
            "somado": foi_somado,
        }

    insumos_map = {}
    for item in itens_op:
        dados_item = _obter_total_unidades(item)
        if dados_item is None:
            continue

        df_comp, total_unidades, total_unidades_caixa = dados_item
        cod_produto_origem = str(item.get("codigo_caixa", "")).strip()

        for _, row in df_comp.iterrows():
            _adicionar_insumo(
                insumos_map,
                row,
                total_unidades,
                total_unidades_caixa,
                cod_produto_origem=cod_produto_origem,
            )

    return [_montar_resultado(item) for item in insumos_map.values()]


OP_FOLDER = "ordens_producao_scf"
os.makedirs(OP_FOLDER, exist_ok=True)


def carregar_historico_ops():
    """Carrega o histórico de ordens de produção salvas em arquivos JSON."""
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
# INTERFACE GRÁFICA NICEGUI
# -----------------------------------------------------------------------------
@ui.page("/")
def main_page():
    """Render the PCP dashboard and operation workflow UI."""
    # pylint: disable=too-many-locals,too-many-statements
    ui.colors(primary="#1E40AF", secondary="#0D9488", accent="#F59E0B", dark="#0F172A")

    # Injeta o estilo CSS para forçar o negrito e a cor escura nas labels do Quasar
    ui.add_head_html("""
    <style>
        /* Ajuste do tamanho e peso das labels para manter proporção */
        .q-field__label {
            font-weight: 700 !important;
            font-size: 0.95rem !important;
            color: #1e293b !important;
        }

        .q-field--float .q-field__label {
            font-size: 0.90rem !important;
            font-weight: 700 !important;
            transform: translateY(-120%) scale(1) !important;
        }

        .q-field--labeled .q-field__native,
        .q-field--labeled .q-field__prefix,
        .q-field--labeled .q-field__suffix {
            padding-top: 20px !important;
        }
    </style>
    """)

    # Restante do código da interface...

    with ui.header().classes(
        "bg-primary text-white p-4 items-center justify-between shadow-lg"
    ):
        with ui.row().classes("items-center gap-3"):
            ui.icon("factory", size="32px")
            with ui.column().classes("gap-0"):
                ui.label("PCP - Linha de Alimentos Faleiro").classes(
                    "text-xl font-bold tracking-wide"
                )
                ui.label(
                    "Motor de Cálculo de Receitas & Mapeamento SCF (DuckDB + NDJSON)"
                ).classes("text-xs opacity-80")

        with ui.row().classes("items-center gap-3"):
            badge_fonte = ui.badge(
                f"Fonte: {estado_dados['fonte_atual']}", color="teal"
            ).classes("text-xs px-3 py-1 font-mono")

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
        tab_lancamento = ui.tab(
            "Gerador de OP / Explosão Insumos", icon="add_shopping_cart"
        )
        tab_historico = ui.tab(
            "Histórico de OPs Enviadas ao SCF", icon="format_list_bulleted"
        )

    with ui.tab_panels(tabs, value=tab_lancamento).classes("w-full bg-slate-50 p-6"):
        with ui.tab_panel(tab_lancamento).classes("gap-6"):
            with ui.card().classes(
                "w-full p-5 border border-slate-200 shadow-sm rounded-xl bg-white mb-6"
            ):
                ui.label(
                    "1. Lançamento da Ordem de Produção (Intenção PCP Multi-Produto)"
                ).classes("text-xl font-extrabold text-slate-800 mb-2")

                with ui.row().classes("w-full items-center gap-4 flex-wrap"):
                    select_prod = (
                        ui.select(
                            options=dict_produtos,
                            label="Selecione o Produto Final (Part Number)",
                            value=list(dict_produtos.keys())[0]
                            if dict_produtos
                            else None,
                            with_input=True,
                        )
                        .classes("w-96")
                        .props('input-class="text-base font-bold text-slate-900"')
                    )

                    input_cx = (
                        ui.number(label="Caixas (CX)", value=0, min=0, format="%.0f")
                        .classes("w-32")
                        .props('input-class="text-base font-bold text-slate-900"')
                    )
                    input_pct = (
                        ui.number(label="Pacotes (PCT)", value=0, min=0, format="%.0f")
                        .classes("w-32")
                        .props('input-class="text-base font-bold text-slate-900"')
                    )

                    input_und = (
                        ui.number(label="Unidades (UNI)", value=0, min=0, format="%.0f")
                        .classes("w-32")
                        .props('input-class="text-base font-bold text-slate-900"')
                    )

                    # Card dinâmico para a Memória de Cálculo de Unidades
                    # Card/Label da Memória de Cálculo com fonte maior e destaque
                    label_memoria = ui.label("").classes(
                        "w-full text-sm font-mono text-blue-900 font-bold mt-2 bg-blue-100 p-3 rounded-lg border border-blue-300 shadow-sm"
                    )

                    def atualizar_preview_memoria():
                        cod = select_prod.value
                        cx = converter_para_float(input_cx.value)
                        pct = converter_para_float(input_pct.value)
                        und = converter_para_float(input_und.value)

                        if not cod:
                            label_memoria.text = ""
                            return

                        desc_prod = dict_produtos.get(str(cod), "")
                        pct_cx, uni_pct = obter_fatores_embalagem(str(cod), desc_prod)

                        mem_txt = gerar_memoria_calculo_unidades(
                            cx, pct, und, pct_cx, uni_pct
                        )
                        label_memoria.text = f"📊 Memória de Cálculo: {mem_txt}"

                    input_cx.on_value_change(atualizar_preview_memoria)
                    input_pct.on_value_change(atualizar_preview_memoria)
                    input_und.on_value_change(atualizar_preview_memoria)
                    select_prod.on_value_change(atualizar_preview_memoria)

                    def adicionar_item_op():
                        cod = select_prod.value
                        cx = converter_para_float(input_cx.value)
                        pct = converter_para_float(input_pct.value)
                        und = converter_para_float(input_und.value)

                        if cx == 0 and pct == 0 and und == 0:
                            ui.notify(
                                "Informe ao menos uma quantidade!", type="warning"
                            )
                            return

                        desc_prod = dict_produtos.get(str(cod), "")
                        pct_cx, uni_pct = obter_fatores_embalagem(str(cod), desc_prod)

                        memoria_txt = gerar_memoria_calculo_unidades(
                            cx, pct, und, pct_cx, uni_pct
                        )

                        ordem_itens.append(
                            {
                                "codigo_caixa": cod,
                                "caixas": cx,
                                "pacotes": pct,
                                "unidades": und,
                                "memoria_calculo_unidades": memoria_txt,
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
                            label_memoria.text = ""
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
                                "linha_producao": "Linha Faleiro",
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
                            label_memoria.text = ""
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
                        "name": "cod_insumo",
                        "label": "Código",
                        "field": "cod_insumo",
                        "align": "left",
                    },
                    {
                        "name": "desc_insumo",
                        "label": "Descrição do Insumo",
                        "field": "desc_insumo",
                        "align": "left",
                        "html": True,  # <--- CRÍTICO para permitir renderização de estilos inline
                    },
                    {
                        "name": "linha",
                        "label": "Linha",
                        "field": "linha",
                        "align": "left",
                    },
                    {
                        "name": "lote_kg_str",
                        "label": "Lote Padrão",
                        "field": "lote_kg_str",
                        "align": "right",
                    },
                    {
                        "name": "unidade",
                        "label": "Unidade",
                        "field": "unidade",
                        "align": "center",
                    },
                    {
                        "name": "num_lotes",
                        "label": "Nº Receitas (Regra 0.5)",
                        "field": "num_lotes",
                        "align": "right",
                    },
                    {
                        "name": "total_bruto_str",
                        "label": "Total bruto a preparar",
                        "field": "total_bruto_str",
                        "align": "right",
                    },
                ]

                tabela = ui.table(
                    columns=colunas_tabela, rows=[], row_key="cod_insumo"
                ).classes("w-full shadow-none border border-slate-200 rounded-lg")

                # Slot nativo do Quasar para renderizar a etiqueta em Azul Claro suave
                tabela.add_slot(
                    "body-cell-desc_insumo",
                    """
                    <q-td :props="props">
                        <template v-if="props.row.somado">
                            <span class="bg-blue-1 text-blue-10 text-bold q-pa-xs rounded border border-blue-3">
                                🔀 {{ props.row.desc_insumo }}
                            </span>
                        </template>
                        <template v-else>
                            {{ props.row.desc_insumo }}
                        </template>
                    </q-td>
                    """,
                )

                def atualizar_tabela_insumos():
                    dados = calcular_ordem_duckdb(ordem_itens)
                    tabela.rows = dados
                    tabela.update()

        with ui.tab_panel(tab_historico):
            with ui.card().classes(
                "w-full p-5 border border-slate-200 shadow-sm rounded-xl bg-white"
            ):
                ui.label("Histórico de Ordens de Produção Confirmadas").classes(
                    "text-base font-bold text-slate-800 mb-2"
                )
                ui.label(
                    "Consulta das Ordens de Produção salvas em JSON para o SCF."
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


if __name__ in {"__main__", "__mp_main__"}:
    ui.run(title="PCP Faleiro - NiceGUI & DuckDB", port=8085, reload=False)
