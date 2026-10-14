# 🏭 Sistema de PCP - Linha de Alimentos Faleiro

Uma aplicação moderna, leve e de alta performance desenvolvida em **Python** para Planejamento e Controle da Produção (PCP). O sistema realiza a explosão instantânea de ordens de produção em insumos e semiacabados (massas, recheios e acabamentos) e calcula o loteamento exato de receitas para a cozinha.

---

## 🌟 Destaques do Projeto

* **Arquitetura NDJSON + DuckDB**: Consultas analíticas em fração de milissegundos sobre dados hierárquicos aninhados (Bill of Materials / Ficha Técnica) sem gargalos de *JOINs* relacionais.
* **Interface Dinâmica (NiceGUI)**: UI reativa e moderna para o operador do PCP lançar ordens de produção por Caixas, Pacotes ou Unidades avulsas.
* **Arredondamento Inteligente de Lotes**: Cálculo automático de receitas necessárias respeitando o lote padrão e a regra de produção (múltiplos de 0,5 receita).
* **Gestão Leve de Dependências**: Configurado e gerenciado com o **`uv`**, dispensando infraestruturas pesadas como Docker ou bases de dados complexas.

---
## 🔀 Consolidação Multi-Produto & Explosão de Dependências (MRP)

O dashboard conta com um motor de explosão de **Bill of Materials (BOM)** em **DuckDB**, capaz de consolidar demandas de insumos a partir de intenções de produção multi-produto na Ordem de Produção (OP).

### 🚀 Destaques da Funcionalidade

- **Arcabouço Fixo de Conversão de Unidades**: Normalização automática e imutável do peso unitário dos insumos (`threshold` de `0.20 kg`), garantindo precisão matemática independente da ficha técnica (itens por caixa vs. itens por unidade física individual).
- **Consolidação Inteligente de Insumos Compartilhados**: Agrupamento automático de matérias-primas e semiacabados comuns a múltiplos produtos finais lançados na OP.
- **Sinalização Visual no PCP**: Insumos consolidados de múltiplos produtos são sinalizados dinamicamente na tabela com a etiqueta **Azul Claro (`bg-blue-1 text-blue-10`)** e o ícone `🔀 (Soma de N produtos)`.
- **Cálculo de Lotes e Regra de Arredondamento (0.5)**: Determinação exata do número de receitas e do total bruto a preparar com base no peso do lote padrão de cada receita.

---

## 📐 Estrutura do Banco / Modelo de Dados

"O projeto adota a separação entre a ***Matemática de Embalagem*** (fatores de conversão: pacotes por caixa, unidades por pacote e tabuleiros) e a ***Ficha Técnica de Produção*** (ingredientes e insumos do produto)."

📊 Modelo da Planilha de Origem (Modelo_Ref_PCP_NDJSON.xlsx)
├── Aba 'PRODUTOS' (Cadastro Comercial)
│    └── Codigo_Caixa | Descricao_Caixa | Linha | Pct_Por_Cx | Uni_Por_Pct | Qtd_Por_Tabuleiro
└── Aba 'FICHA_TECNICA' (BOM Normalizado / Long Format)
└── Codigo_Produto | Tipo_Componente | Codigo_Insumo | Peso_Unid_KG | Peso_Lote_Receita_KG

Ao iniciar, o motor de dados aninha as fichas técnicas no formato **NDJSON** em memória no DuckDB:

```json
```json
{
  "codigo_caixa": "101218",
  "descricao_caixa": "(151) CIGARRETE TRADICIONAL CX C/30",
  "linha": "Linha Digrano",
  "pct_por_cx": 3,
  "uni_por_pct": 10,
  "composicoes": [
    {
      "tipo": "MASSA",
      "codigo_insumo": 207006,
      "descricao_insumo": "SEMIACABADO MASSA CIGARRETE",
      "peso_unid_kg": 0.07,
      "peso_lote_receita_kg": 86.55
    },
    {
      "tipo": "RECHEIO",
      "codigo_insumo": 201001,
      "descricao_insumo": "SEMIACABADO PRESUNTO FATIADO",
      "peso_unid_kg": 0.028,
      "peso_lote_receita_kg": 1.0
    }
  ]
}
```

🛠️ Tecnologias Utilizadas
Python 3.12+: Linguagem principal.

uv: Gerenciador de pacotes e ambientes virtuais ultrarrápido.

NiceGUI: Framework web reativo baseado em FastAPI e Vue.js.

DuckDB: Banco de dados colunar analítico operando em memória sobre estruturas JSON/NDJSON.

Pandas & OpenPyXL: Leitura e manipulação de planilhas Excel.

🚀 Como Executar o Projeto Localmente
Pré-requisitos
Certifique-se de ter o Python e o gerenciador uv instalados na máquina.

```Bash
# Instalação do uv (se necessário)
pip install uv
```

Passo a Passo
1 - Clonar o Repositório:

```Powershell
git clone https://github.com/linduarte/pcp-digrano-demo.git
cd pcp-digrano-demo
```

2 - Executar a Aplicação:
O uv irá criar o ambiente virtual e sincronizar todas as dependências do pyproject.toml automaticamente:

```Powershell
uv run app_nicegui_pcp.py
```

3 - Acessar a Interface:
Abra o seu navegador de preferência e acesse:
👉 http://localhost:8085

🖥️ Telas e Uso da Aplicação
Lançamento de Ordens: Selecione o produto desejado na lista, introduza a quantidade pretendida (Caixas, Pacotes e/ou Unidades) e clique em "Adicionar Lote".

1 - Explosão Consolidada: A tabela inferior exibirá em tempo real:

2 - Necessidade Líquida (KG): Peso exato consumido pela demanda.

    Lote Padrão: Tamanho da receita na fábrica.

    Nº de Receitas (0.5): Quantidade ajustada de lotes a serem produzidos (arredondado para o meio lote superior).

    Total Bruto a Preparar (KG): Quantidade final a enviar para a cozinha/misturador.



## 📄 Documentação Arquitetural e Fluxo de Integração (PCP / SCF / ERP)

### 📌 Esclarecimentos de Conceito e Arquitetura

#### 1. Formato de Exportação e Payload JSON

O envio das Ordens de Produção (OPs) é realizado nativamente em formato **JSON**. Ao acionar a confirmação da ordem no painel, o sistema compila a demanda consolidada e gera um arquivo `.json` estruturado na pasta `ordens_producao_scf/`.

O contrato de dados é composto por dois blocos principais:

* **`programacao_produtos`**: Contém a intenção comercial definida pelo operador no PCP, preservando as entradas em Caixas (CX), Pacotes (PCT) e Unidades (UNI), além da memória de cálculo auditável.
* **`explosao_insumos`**: Apresenta a consolidação das necessidades líquidas de matéria-prima e a quantidade final de receitas arredondadas conforme os lotes industriais.

---

#### 2. O que é o "Gerador de OP / Explosão de Insumos"?

Esta aba concentra as duas etapas centrais do processo de Planejamento e Controle da Produção:

* **Gerador de OP (Lançamento de Demanda Multi-Produto)**:Interface operacional para traduzir previsões de vendas, pedidos ou metas de estoque em ordens reais de fabricação. Aceita múltiplas combinações de embalagens para o mesmo item e exibe a memória de cálculo física unificada (total de unidades salgadas).
* **Explosão de Insumos (BOM Explosion)**:
  Motor matemático baseado em DuckDB que percorre dinamicamente a árvore de produto (Ficha Técnica / Árvore BOM do SCF). A engine decompoe a necessidade do produto acabado em seus constituintes intermediários (massa, recheio, frios), normaliza os consumos unitários e aplica a **Regra do Lote 0.5** para cálculo do número exato de receitas a preparar.

---

### 🔄 Fluxo de Envio Simultâneo (PCP ➔ SCF & ERP)

Para assegurar o alinhamento entre o chão de fábrica (SCF) e a gestão administrativa/financeira (ERP), as Ordens de Produção geradas pelo PCP operam no seguinte fluxo de integração:

```
                         ┌─────────────────────────────┐
                         │   PCP Dashboard (NiceGUI)   │
                         └──────────────┬──────────────┘
                                        │
                                        ▼  (Gera Payload JSON com OP_ID)
                         ┌─────────────────────────────┐
                         │   Payload JSON Estruturado  │
                         └──────────────┬──────────────┘
                                        │
                 ┌──────────────────────┴──────────────────────┐
                 ▼                                             ▼
  ┌─────────────────────────────┐               ┌─────────────────────────────┐
  │         Módulo SCF          │               │         Módulo ERP          │
  │     (Chão de Fábrica)       │               │ (Gestão de Estoque/Custos)  │
  ├─────────────────────────────┤               ├─────────────────────────────┤
  │ • Apontamento de Lotes      │               │ • Baixa de Matéria-Prima    │
  │ • Programação de Linha      │               │ • Custo Industrial / COGS   │
  │ • Controle de Preparação    │               │ • Faturamento & Ordens      │
  └─────────────────────────────┘               └─────────────────────────────┘
```

#### Estratégias para Conexão com o ERP:

1. **Integração Direta via Banco de Dados (Staging Table / Stored Procedures)**:Mapeamento de views e tabelas de interface no SQL Server/PostgreSQL do ERP onde os dados do payload JSON são inseridos diretamente.
2. **Consumo de API REST / Webhook**:Envio assíncrono via requisição `HTTP POST` disparada pelo NiceGUI para o endpoint de importação de ordens do ERP.
3. **Monitoramento de Pasta (Folder Watcher)**:
   Serviço em segundo plano no ERP que consome e processa automaticamente os arquivos JSON salvos no diretório compartilhado.


📄 Licença
Este projeto foi desenvolvido para fins de demonstração técnica e otimização de processos fabris.
