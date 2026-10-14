"""Script para inspecionar produtos e suas estruturas no SCF."""

try:
    import pyodbc  # type: ignore[import-not-found]
except ModuleNotFoundError as exc:
    raise ModuleNotFoundError(
        "pyodbc não está instalado. Instale com: pip install pyodbc"
    ) from exc

# Utilize aqui a mesma string/configuração de conexão do seu sincronizar_scf.py
CONN_STR = (
    "DRIVER={ODBC Driver 17 for SQL Server};"
    "SERVER=localhost;"
    "DATABASE=SCF;"
    "Trusted_Connection=yes;"
)

# Pylint/astroid não consegue introspectar membros de extensão C do pyodbc.
conn = pyodbc.connect(CONN_STR)  # type: ignore[attr-defined]  # pylint: disable=c-extension-no-member
cursor = conn.cursor()

print("\n--- ESTRUTURA DO PRODUTO PARA SCF001 / CHARUTINHO ---")
cursor.execute("""
    SELECT DISTINCT
        RTRIM(v.codigoProduto) AS cod_produto_view,
        RTRIM(v.codigoInsumo) AS cod_insumo_view,
        v.quantidadeInsumo
    FROM dbo.viewEstruturaProduto v
    WHERE UPPER(v.codigoProduto) LIKE '%SCF%'
       OR UPPER(v.codigoProduto) LIKE '%11810%'
       OR UPPER(v.codigoInsumo) LIKE '%201001%'
       OR UPPER(v.codigoInsumo) LIKE '%PRESUNTO%'
""")

linhas = cursor.fetchall()
if not linhas:
    print("Nenhum registro encontrado na viewEstruturaProduto!")
else:
    for linha in linhas:
        print(
            f"codigoProduto na View: '{linha[0]}' | codigoInsumo: '{linha[1]}' | Qtd: {linha[2]}"
        )
