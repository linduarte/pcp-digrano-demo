"""Script para sincronizar produtos do SCF para um arquivo NDJSON."""

import json
import os
import re

import pyodbc  # type: ignore[import-not-found]
from dotenv import load_dotenv

# Carrega as variáveis de ambiente do ficheiro .env
load_dotenv()

DB_CONFIG = {
    "driver": os.getenv("SCF_DB_DRIVER", "SQL Server"),
    "server": os.getenv("SCF_DB_SERVER", "192.168.0.61"),
    "database": os.getenv("SCF_DB_NAME", "SCF"),
    "user": os.getenv("SCF_DB_USER", "SCF_user"),
    "password": os.getenv("SCF_DB_PASS", ""),
}

# Consulta SQL simplificada, explícita e compatível com o SQL Server
QUERY_SCF = """
WITH CTE_ArvoreBOM AS (
    SELECT 
        RTRIM(e.codigoProduto) COLLATE DATABASE_DEFAULT AS codigo_pai,
        RTRIM(e.codigoInsumo) COLLATE DATABASE_DEFAULT AS codigo_filho,
        CAST(e.quantidadeInsumo AS FLOAT) AS qtd_acumulada,
        1 AS profundidade
    FROM dbo.viewEstruturaProduto e

    UNION ALL

    SELECT 
        a.codigo_pai,
        RTRIM(e2.codigoInsumo) COLLATE DATABASE_DEFAULT AS codigo_filho,
        CAST(a.qtd_acumulada * e2.quantidadeInsumo AS FLOAT) AS qtd_acumulada,
        a.profundidade + 1
    FROM CTE_ArvoreBOM a
    INNER JOIN dbo.viewEstruturaProduto e2 
        ON a.codigo_filho = RTRIM(e2.codigoProduto) COLLATE DATABASE_DEFAULT
    WHERE a.profundidade < 5
)
SELECT 
    p.codigoInterno AS id_interno_scf,
    ISNULL(NULLIF(RTRIM(p.partNumber), ''), CAST(p.codigoInterno AS VARCHAR)) AS codigo_caixa,
    p.nome AS descricao_caixa,
    ISNULL(l.nome, 'GERAL') AS linha,
    ISNULL(NULLIF(p.padraoApontamento1, 0), 1) AS pct_por_cx,
    ISNULL(NULLIF(p.padraoApontamento2, 0), 1) AS uni_por_pct,
    ISNULL(p.quantidadeBandeja, 0) AS qtd_por_tabuleiro,
    p.peso AS peso_unitario_kg,
    (
        SELECT DISTINCT
            ISNULL(MAX(c.nome), 'SEMIACABADOS') AS tipo,
            RTRIM(i_sub.codigo_filho) AS codigo_insumo,
            COALESCE(
                NULLIF(RTRIM(MAX(i.nomeReduzido)) COLLATE DATABASE_DEFAULT, ''),
                NULLIF(RTRIM(MAX(pg_ins.nome)) COLLATE DATABASE_DEFAULT, ''),
                RTRIM(i_sub.codigo_filho) COLLATE DATABASE_DEFAULT
            ) AS descricao_insumo,
            MAX(i_sub.qtd_acumulada) AS peso_unid_kg,
            COALESCE(MAX(pg_ins.peso), 1.0) AS peso_lote_receita_kg,
            'KG' AS unidade
        FROM CTE_ArvoreBOM i_sub
        LEFT JOIN dbo.produtoGeral pg_ins 
            ON (RTRIM(i_sub.codigo_filho) = RTRIM(pg_ins.partNumber) COLLATE DATABASE_DEFAULT
                OR RTRIM(i_sub.codigo_filho) = CAST(pg_ins.codigoInterno AS VARCHAR) COLLATE DATABASE_DEFAULT)
        LEFT JOIN dbo.insumo i 
            ON (RTRIM(i_sub.codigo_filho) = RTRIM(i.codigoExterno) COLLATE DATABASE_DEFAULT 
                OR RTRIM(i_sub.codigo_filho) = CAST(i.codigoInterno AS VARCHAR(50)) COLLATE DATABASE_DEFAULT)
        LEFT JOIN dbo.categoriaInsumo c 
            ON i.categoriaInsumo = c.codigoInterno
        WHERE 
            (RTRIM(i_sub.codigo_pai) = RTRIM(p.partNumber) COLLATE DATABASE_DEFAULT
             OR RTRIM(i_sub.codigo_pai) = CAST(p.codigoInterno AS VARCHAR) COLLATE DATABASE_DEFAULT
             OR (UPPER(TRIM(p.partNumber)) = 'SCF001' AND RTRIM(i_sub.codigo_pai) = '101235')
             OR (UPPER(TRIM(p.partNumber)) = 'SCF002' AND RTRIM(i_sub.codigo_pai) = '101176')
             OR (UPPER(TRIM(p.partNumber)) = 'SCF003' AND RTRIM(i_sub.codigo_pai) = '102252'))
            AND RTRIM(i_sub.codigo_filho) LIKE '20%'
        GROUP BY RTRIM(i_sub.codigo_filho)
        FOR JSON PATH
    ) AS composicoes_json
FROM dbo.produtoGeral p
LEFT JOIN dbo.linha l ON p.linha = l.codigoInterno
WHERE (UPPER(TRIM(p.partNumber)) LIKE '10%' OR UPPER(TRIM(p.partNumber)) LIKE 'SCF%')
  AND NULLIF(TRIM(p.nome), '') IS NOT NULL;
"""
# Mapeamento estático de segurança para semiacabados SCF que não possuem estrutura no ERP
COMPOSICOES_MANUAIS_SCF = {
    "SCF001": [
        {
            "tipo": "SEMIACABADOS",
            "cod_insumo": "201001",
            "desc_insumo": "SEMIACABADO PRESUNTO FATIADO - 1,00KG - R",
            "peso_unid_kg": 0.028,
            "peso_lote_receita_kg": 1.0,
            "unidade": "KG"
        },
        {
            "tipo": "SEMIACABADOS",
            "cod_insumo": "204001",
            "desc_insumo": "SEMIACABADO MUSSARELA FATIADA - 1,00KG - R",
            "peso_unid_kg": 0.014,
            "peso_lote_receita_kg": 1.0,
            "unidade": "KG"
        }
    ],
    "SCF002": [
        {
            "tipo": "SEMIACABADOS",
            "cod_insumo": "201002",
            "desc_insumo": "SEMIACABADO FRANGO DESFIADO - 1,00KG - R",
            "peso_unid_kg": 0.028,
            "peso_lote_receita_kg": 1.0,
            "unidade": "KG"
        },
        {
            "tipo": "SEMIACABADOS",
            "cod_insumo": "204001",
            "desc_insumo": "SEMIACABADO MUSSARELA FATIADA - 1,00KG - R",
            "peso_unid_kg": 0.014,
            "peso_lote_receita_kg": 1.0,
            "unidade": "KG"
        }
    ]
}

def aplicar_composicoes_resilientes(codigo_caixa: str, composicoes):
    """Retorna composições do SQL ou um fallback manual para SCFs sem ficha."""
    codigo_caixa = str(codigo_caixa or "").strip().upper()
    if not composicoes and codigo_caixa in COMPOSICOES_MANUAIS_SCF:
        return COMPOSICOES_MANUAIS_SCF[codigo_caixa]
    return composicoes


def executar_sincronizacao():
    """Sincroniza os produtos do SCF para um ficheiro NDJSON."""
    connection_string = (
        f"DRIVER={{{DB_CONFIG['driver']}}};"
        f"SERVER={DB_CONFIG['server']};"
        f"DATABASE={DB_CONFIG['database']};"
        f"UID={DB_CONFIG['user']};"
        f"PWD={DB_CONFIG['password']}"
    )

    connection = None
    try:
        connection = pyodbc.connect(connection_string)  # pylint: disable=c-extension-no-member
        cursor = connection.cursor()
        cursor.execute(QUERY_SCF)
        rows = cursor.fetchall()

        produtos = []
        for row in rows:
            id_interno = str(row[0]) if row[0] is not None else ""
            part_num = str(row[1]).strip() if row[1] is not None else id_interno
            desc_caixa = str(row[2]).strip() if row[2] is not None else ""
            nome_linha = str(row[3]).strip() if row[3] is not None else "GERAL"
            pct_cx = int(row[4]) if row[4] is not None else 1
            uni_pct = int(row[5]) if row[5] is not None else 1
            qtd_tab = int(row[6]) if row[6] is not None else 0
            json_comps = row[8] if len(row) > 8 else None

            clean_comps = []
            if json_comps:
                try:
                    clean_comps = json.loads(json_comps)
                    for comp in clean_comps:
                        if not isinstance(comp, dict):
                            continue
                        desc_insumo = str(comp.get("descricao_insumo", "")).strip()
                        match = re.search(r"-\s*([\d,.]+)\s*(?:KG)?\s*-", desc_insumo)
                        if match:
                            try:
                                peso_lote = float(match.group(1).replace(",", "."))
                                comp["peso_lote_receita_kg"] = peso_lote
                            except ValueError:
                                pass
                except json.JSONDecodeError:
                    clean_comps = []

            produtos.append(
                {
                    "codigo_caixa": part_num,
                    "codigo_interno_scf": id_interno,
                    "descricao_caixa": desc_caixa,
                    "linha": nome_linha,
                    "pct_por_cx": pct_cx,
                    "uni_por_pct": uni_pct,
                    "qtd_por_tabuleiro": qtd_tab,
                    "composicoes": clean_comps,
                }
            )

        with open("fichas_tecnicas_scf.ndjson", "w", encoding="utf-8") as handle:
            for produto in produtos:
                handle.write(json.dumps(produto, ensure_ascii=False) + "\n")

        print(
            f"Sucesso! {len(produtos)} produtos sincronizados em 'fichas_tecnicas_scf.ndjson'."
        )
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    executar_sincronizacao()
