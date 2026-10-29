import json                      # para baixar/carregar os dados em arquivo .json
from datetime import datetime    # para mostrar a hora da última atualização

import pandas as pd              # tabelas (DataFrame)
import plotly.express as px      # gráficos bonitos e interativos
import requests                  # para chamar a API do Banco Central
import streamlit as st           # a interface web
import yfinance as yf            # cotações (ações, FIIs, dólar, cripto...)

st.set_page_config(page_title="Assistente Financeiro", page_icon="💰", layout="wide")

CLASSES = [
    "Renda Fixa Pós (Selic/CDI)",
    "Renda Fixa IPCA+",
    "Ações BR",
    "FIIs",
    "Internacional",
    "Cripto",
]

ALOCACAO_POR_PERFIL = {
    "Conservador": {"Renda Fixa Pós (Selic/CDI)": 60, "Renda Fixa IPCA+": 25,
                    "Ações BR": 5, "FIIs": 5, "Internacional": 5, "Cripto": 0},
    "Moderado":    {"Renda Fixa Pós (Selic/CDI)": 25, "Renda Fixa IPCA+": 25,
                    "Ações BR": 25, "FIIs": 10, "Internacional": 15, "Cripto": 0},
    "Arrojado":    {"Renda Fixa Pós (Selic/CDI)": 10, "Renda Fixa IPCA+": 15,
                    "Ações BR": 40, "FIIs": 10, "Internacional": 20, "Cripto": 5},
}

SERIES_BCB = {
    "Selic (meta % a.a.)": 432,
    "CDI (% a.a.)": 4389,
    "IPCA 12 meses (%)": 13522,
}

INDICES = {
    "Ibovespa": "^BVSP",
    "Dólar (R$)": "BRL=X",
    "S&P 500": "^GSPC",
    "Bitcoin (US$)": "BTC-USD",
}

PERGUNTAS = {
    "queda": ("Se seus investimentos caíssem 20% em um mês, você...",
              {"Venderia tudo para evitar mais perdas": 1,
               "Esperaria se recuperar": 2,
               "Compraria mais aproveitando o preço baixo": 3}),
    "experiencia": ("Sua experiência com investimentos:",
                    {"Só poupança / nunca investi": 1,
                     "Já invisto em renda fixa": 2,
                     "Invisto em ações, FIIs ou outros de risco": 3}),
    "objetivo": ("Seu principal objetivo:",
                 {"Preservar o dinheiro": 1,
                  "Crescer com segurança": 2,
                  "Maximizar o ganho, aceitando oscilações": 3}),
}

# Colunas da tabela da carteira
COLUNAS_CARTEIRA = ["ticker", "classe", "quantidade", "preco_medio"]

# Valores iniciais (tudo vazio: cada pessoa preenche os seus)
DADOS_PADRAO = {
    "nome": "",
    "idade": 25,
    "renda_mensal": 0.0,
    "despesa_mensal": 0.0,
    "reserva_atual": 0.0,
    "aporte_mensal": 0.0,
    "horizonte_anos": 5,
    "respostas_risco": {"queda": 1, "experiencia": 1, "objetivo": 1},
    "carteira": [],
}

def texto_da_pontuacao(opcoes: dict, pontos) -> str:
    """Descobre qual texto de resposta vale tantos pontos (para marcar o radio)."""
    for texto, valor in opcoes.items():
        if valor == pontos:
            return texto
    return list(opcoes.keys())[0]  # se não achar, usa a primeira opção


def preparar_estado() -> None:
    """Cria os valores iniciais dos campos (só na primeira vez da sessão)."""
    if "iniciado" in st.session_state:
        return
    st.session_state.iniciado = True
    st.session_state.versao = 0          # muda a cada arquivo carregado (reinicia a tabela)
    st.session_state.carteira_base = []  # carteira que a tabela mostra ao abrir
    st.session_state.carteira_atual = [] # carteira com as edições mais recentes
    for chave in ("nome", "idade", "renda_mensal", "despesa_mensal",
                  "reserva_atual", "aporte_mensal", "horizonte_anos"):
        st.session_state[chave] = DADOS_PADRAO[chave]
    for chave, (pergunta, opcoes) in PERGUNTAS.items():
        st.session_state[f"risco_{chave}"] = texto_da_pontuacao(
            opcoes, DADOS_PADRAO["respostas_risco"][chave])


def numero_seguro(valor, minimo: float, maximo: float, padrao: float) -> float:
    """Converte para número e limita entre mínimo e máximo (arquivo pode vir bagunçado)."""
    try:
        numero = float(valor)
    except (TypeError, ValueError):
        return padrao
    if numero != numero:  # NaN (não é número)
        return padrao
    return min(max(numero, minimo), maximo)


def aplicar_dados(bruto) -> None:
    """Valida o conteúdo de um arquivo carregado e coloca nos campos da tela."""
    if not isinstance(bruto, dict):
        raise ValueError("O arquivo não tem o formato esperado.")

    st.session_state.nome = str(bruto.get("nome", ""))[:60]
    st.session_state.idade = int(numero_seguro(bruto.get("idade"), 16, 100, 25))
    st.session_state.horizonte_anos = int(numero_seguro(bruto.get("horizonte_anos"), 1, 30, 5))
    for chave in ("renda_mensal", "despesa_mensal", "reserva_atual", "aporte_mensal"):
        st.session_state[chave] = numero_seguro(bruto.get(chave), 0.0, 1e12, 0.0)

    respostas = bruto.get("respostas_risco", {})
    if not isinstance(respostas, dict):
        respostas = {}
    for chave, (pergunta, opcoes) in PERGUNTAS.items():
        st.session_state[f"risco_{chave}"] = texto_da_pontuacao(opcoes, respostas.get(chave, 1))

    carteira = []
    itens = bruto.get("carteira", [])
    for item in (itens[:200] if isinstance(itens, list) else []):  # no máximo 200 linhas
        if not isinstance(item, dict) or item.get("classe") not in CLASSES:
            continue
        ticker = str(item.get("ticker", "")).strip()[:30]
        if not ticker:
            continue
        carteira.append({
            "ticker": ticker,
            "classe": item["classe"],
            "quantidade": numero_seguro(item.get("quantidade"), 0.0, 1e12, 0.0),
            "preco_medio": numero_seguro(item.get("preco_medio"), 0.0, 1e12, 0.0),
        })
    st.session_state.carteira_base = carteira
    st.session_state.carteira_atual = carteira
    st.session_state.versao += 1  # força a tabela e o botão de upload a recomeçarem

@st.cache_data(ttl=60)
def buscar_serie_bcb(codigo: int):
    """Devolve o último valor de uma série do Banco Central (ou None se falhar)."""
    url = f"https://api.bcb.gov.br/dados/serie/bcdata.sgs.{codigo}/dados/ultimos/1?formato=json"
    try:
        resposta = requests.get(url, timeout=8)
        resposta.raise_for_status()                 # erro se o status não for 200
        return float(resposta.json()[-1]["valor"])  # último valor da lista
    except Exception:
        return None  # se der erro de rede, o app continua funcionando


@st.cache_data(ttl=60)
def buscar_cotacao(ticker: str):
    """Devolve (preço atual, variação % do dia) de um ticker, ou (None, None)."""
    try:
        historico = yf.Ticker(ticker).history(period="5d")["Close"].dropna()
        if len(historico) == 0:
            return None, None
        preco = float(historico.iloc[-1])
        # variação em relação ao fechamento anterior (se existir)
        variacao = (preco / float(historico.iloc[-2]) - 1) * 100 if len(historico) > 1 else 0.0
        return preco, variacao
    except Exception:
        return None, None


def normalizar_ticker(ticker: str, classe: str) -> str:
    """Ações e FIIs brasileiros precisam do sufixo '.SA' no Yahoo Finance."""
    ticker = ticker.strip().upper()
    if classe in ("Ações BR", "FIIs") and "." not in ticker:
        return ticker + ".SA"
    return ticker

def calcular_perfil(dados: dict) -> str:
    """Soma os pontos das respostas e ajusta por idade e horizonte."""
    pontos = sum(dados["respostas_risco"].values())  # vai de 3 a 9

    # Quem tem mais tempo pela frente pode aceitar mais risco
    if dados["horizonte_anos"] >= 10:
        pontos += 1
    elif dados["horizonte_anos"] <= 2:
        pontos -= 1

    if dados["idade"] >= 60:
        pontos -= 1

    if pontos <= 5:
        return "Conservador"
    if pontos <= 8:
        return "Moderado"
    return "Arrojado"


def montar_carteira(linhas: list) -> pd.DataFrame:
    """Para cada ativo, busca o preço atual e calcula valor e lucro."""
    registros = []
    for item in linhas:
        if not str(item.get("ticker", "")).strip():
            continue  # ignora linhas vazias
        ticker = normalizar_ticker(item["ticker"], item["classe"])
        preco, variacao = buscar_cotacao(ticker)

        # Se não achou cotação (ex.: Tesouro Direto, CDB), usa o preço médio
        manual = preco is None
        preco_usado = item["preco_medio"] if manual else preco

        investido = item["quantidade"] * item["preco_medio"]
        valor_atual = item["quantidade"] * preco_usado
        registros.append({
            "Ativo": item["ticker"].upper(),
            "Classe": item["classe"],
            "Quantidade": item["quantidade"],
            "Preço médio": item["preco_medio"],
            "Preço atual": preco_usado,
            "Variação dia %": 0.0 if variacao is None else variacao,
            "Investido": investido,
            "Valor atual": valor_atual,
            "Lucro R$": valor_atual - investido,
            "Lucro %": (valor_atual / investido - 1) * 100 if investido else 0.0,
            "Cotação manual": manual,
        })
    return pd.DataFrame(registros)


def retorno_esperado_anual(classe: str, cdi: float, ipca: float) -> float:
    premissas = {
        "Renda Fixa Pós (Selic/CDI)": cdi,
        "Renda Fixa IPCA+": ipca + 6.0,   # inflação + juro real de ~6%
        "Ações BR": cdi + 3.0,            # prêmio de risco sobre o CDI
        "FIIs": cdi + 1.0,
        "Internacional": cdi + 2.0,
        "Cripto": cdi + 5.0,
    }
    return premissas[classe]


def projetar_patrimonio(inicial: float, aporte: float, taxa_anual: float, anos: int) -> pd.DataFrame:
    """Simula mês a mês: saldo = saldo * (1 + taxa_mensal) + aporte."""
    taxa_mensal = (1 + taxa_anual / 100) ** (1 / 12) - 1  # converte taxa anual em mensal
    saldo, linhas = inicial, []
    for mes in range(0, anos * 12 + 1):
        linhas.append({"Mês": mes, "Patrimônio": saldo})
        saldo = saldo * (1 + taxa_mensal) + aporte
    return pd.DataFrame(linhas)


def formatar_reais(valor: float) -> str:
    """1234.5 -> 'R$ 1.234,50' (padrão brasileiro)."""
    texto = f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"R$ {texto}"


# ----------------------------------------------------------------------
# 6) BARRA LATERAL: carregar dados + perfil + personalização
# ----------------------------------------------------------------------
preparar_estado()

with st.sidebar:
    with st.expander("📂 Carregar meus dados"):
        st.caption("Escolha o arquivo .json que você baixou da última vez.")
        arquivo = st.file_uploader("Arquivo .json", type="json",
                                   key=f"upload_{st.session_state.versao}")
        if arquivo is not None:
            if arquivo.size > 1_000_000:  # 1 MB é mais que suficiente
                st.error("Arquivo grande demais.")
            else:
                try:
                    aplicar_dados(json.load(arquivo))
                    st.rerun()  # recarrega a tela já com os dados novos
                except ValueError:  # JSON inválido ou formato errado
                    st.error("Não consegui ler esse arquivo. Use um .json baixado deste app.")

    st.header("👤 Seu perfil")

    st.text_input("Nome", key="nome")
    st.number_input("Idade", min_value=16, max_value=100, key="idade")
    st.number_input("Renda mensal (R$)", min_value=0.0, step=100.0, key="renda_mensal")
    st.number_input("Despesas mensais (R$)", min_value=0.0, step=100.0, key="despesa_mensal")
    st.number_input("Reserva de emergência atual (R$)", min_value=0.0, step=100.0, key="reserva_atual")
    st.number_input("Quanto pode investir por mês (R$)", min_value=0.0, step=50.0, key="aporte_mensal")
    st.slider("Horizonte de investimento (anos)", 1, 30, key="horizonte_anos")

    st.subheader("Tolerância a risco")
    for chave, (pergunta, opcoes) in PERGUNTAS.items():
        st.radio(pergunta, list(opcoes.keys()), key=f"risco_{chave}")

    st.header("⚙️ Personalizar")
    atualizar_auto = st.toggle("Atualização automática", value=True)
    intervalo = st.select_slider("Atualizar a cada (segundos)", options=[15, 30, 60, 120, 300], value=60)
    alvo_perfil = st.selectbox(
        "Usar alocação de outro perfil?",
        ["Automático (pelo meu perfil)"] + list(ALOCACAO_POR_PERFIL.keys()),
    )
    meses_reserva = st.slider("Meses de reserva de emergência", 3, 12, 6)

    st.info("🔒 Seus dados ficam só nesta página e somem ao fechá-la. "
            "Use **Baixar meus dados**, na aba Minha carteira, para guardá-los.")

dados = {
    "nome": st.session_state.nome,
    "idade": st.session_state.idade,
    "renda_mensal": st.session_state.renda_mensal,
    "despesa_mensal": st.session_state.despesa_mensal,
    "reserva_atual": st.session_state.reserva_atual,
    "aporte_mensal": st.session_state.aporte_mensal,
    "horizonte_anos": st.session_state.horizonte_anos,
    "respostas_risco": {
        chave: opcoes[st.session_state[f"risco_{chave}"]]
        for chave, (pergunta, opcoes) in PERGUNTAS.items()
    },
    "carteira": st.session_state.carteira_atual,
}

perfil_calculado = calcular_perfil(dados)
perfil_usado = perfil_calculado if alvo_perfil.startswith("Automático") else alvo_perfil


# ----------------------------------------------------------------------
# 7) PAINEL PRINCIPAL (atualizado em tempo real)
# ----------------------------------------------------------------------
def painel_principal():
    """Tudo aqui dentro é reexecutado automaticamente a cada 'intervalo' segundos."""
    saudacao = f", {dados['nome']}" if dados["nome"] else ""
    st.title(f"💰 Assistente Financeiro{saudacao}")
    st.caption(f"Última atualização: {datetime.now():%d/%m/%Y %H:%M:%S}  •  "
               "Ferramenta educacional, não é recomendação de investimento.")

    aba_mercado, aba_carteira, aba_recomendacao, aba_projecao = st.tabs(
        ["📈 Mercado", "🧾 Minha carteira", "🎯 Recomendações", "🔮 Projeções"]
    )

    # Busca os indicadores do Banco Central uma vez (usados em várias abas)
    selic = buscar_serie_bcb(SERIES_BCB["Selic (meta % a.a.)"])
    cdi = buscar_serie_bcb(SERIES_BCB["CDI (% a.a.)"])
    ipca = buscar_serie_bcb(SERIES_BCB["IPCA 12 meses (%)"])
    # Valores de segurança caso a internet falhe
    cdi_uso = cdi if cdi is not None else 10.0
    ipca_uso = ipca if ipca is not None else 4.5

    # ---------------- ABA MERCADO ----------------
    with aba_mercado:
        st.subheader("Juros e inflação (Banco Central)")
        colunas = st.columns(3)
        for coluna, (nome, valor) in zip(colunas, [("Selic meta", selic), ("CDI", cdi), ("IPCA 12m", ipca)]):
            coluna.metric(nome, f"{valor:.2f}%" if valor is not None else "indisponível")

        st.subheader("Índices e moedas")
        colunas = st.columns(len(INDICES))
        for coluna, (nome, simbolo) in zip(colunas, INDICES.items()):
            preco, variacao = buscar_cotacao(simbolo)
            if preco is None:
                coluna.metric(nome, "indisponível")
            else:
                coluna.metric(nome, f"{preco:,.2f}", f"{variacao:+.2f}%")

        if selic is not None and ipca is not None:
            juro_real = ((1 + selic / 100) / (1 + ipca / 100) - 1) * 100
            st.info(f"📌 Juro real aproximado (Selic menos inflação): **{juro_real:.2f}% a.a.** "
                    "Quando é alto, a renda fixa tende a ficar mais atraente.")

    # ---------------- ABA CARTEIRA ----------------
    with aba_carteira:
        st.subheader("Edite sua carteira")
        st.caption("Ações/FIIs: digite só o código (ex.: PETR4). Internacional: AAPL. Cripto: BTC-USD. "
                   "Renda fixa: use qualquer nome e informe o valor no preço médio (não tem cotação automática).")

        tabela_base = pd.DataFrame(st.session_state.carteira_base, columns=COLUNAS_CARTEIRA)
        tabela_editada = st.data_editor(
            tabela_base,
            num_rows="dynamic",               # permite adicionar/remover linhas
            width="stretch",
            key=f"editor_carteira_{st.session_state.versao}",
            column_config={
                "ticker": st.column_config.TextColumn("Ativo"),
                "classe": st.column_config.SelectboxColumn("Classe", options=CLASSES, required=True),
                "quantidade": st.column_config.NumberColumn("Quantidade", min_value=0.0),
                "preco_medio": st.column_config.NumberColumn("Preço médio (R$)", min_value=0.0),
            },
        )
        # Guarda a edição (descarta linhas sem classe ou sem ativo)
        carteira_limpa = [
            linha for linha in tabela_editada.fillna(0).to_dict("records")
            if linha.get("ticker") and linha.get("classe") in CLASSES
        ]
        dados["carteira"] = carteira_limpa
        st.session_state.carteira_atual = carteira_limpa

        # Botão para baixar os dados (precisa vir DEPOIS da tabela, para incluir as edições)
        st.download_button(
            "⬇️ Baixar meus dados (.json)",
            data=json.dumps(dados, ensure_ascii=False, indent=2, default=float),
            file_name="meus_dados_financeiros.json",
            mime="application/json",
            help="Guarde este arquivo. Depois, use 'Carregar meus dados' na barra lateral.",
        )

        carteira = montar_carteira(dados["carteira"])
        if carteira.empty:
            st.warning("Adicione ao menos um ativo para ver a análise.")
        else:
            total_investido = carteira["Investido"].sum()
            total_atual = carteira["Valor atual"].sum()
            lucro = total_atual - total_investido
            c1, c2, c3 = st.columns(3)
            c1.metric("Total investido", formatar_reais(total_investido))
            c2.metric("Valor atual", formatar_reais(total_atual))
            c3.metric("Resultado", formatar_reais(lucro),
                      f"{(lucro / total_investido * 100) if total_investido else 0:+.2f}%")

            esquerda, direita = st.columns([3, 2])
            with esquerda:
                vista = carteira.drop(columns=["Cotação manual"]).round(2)
                st.dataframe(vista, width="stretch", hide_index=True)
                if carteira["Cotação manual"].any():
                    st.caption("ℹ️ Ativos sem cotação online usam o preço médio como valor atual.")
            with direita:
                por_classe = carteira.groupby("Classe", as_index=False)["Valor atual"].sum()
                figura = px.pie(por_classe, names="Classe", values="Valor atual", hole=0.45,
                                title="Distribuição por classe")
                st.plotly_chart(figura, width="stretch")

    # ---------------- ABA RECOMENDAÇÕES ----------------
    with aba_recomendacao:
        st.subheader(f"Seu perfil: **{perfil_calculado}**")
        if perfil_usado != perfil_calculado:
            st.caption(f"Usando a alocação do perfil {perfil_usado} (escolhido na barra lateral).")

        carteira = montar_carteira(dados["carteira"])
        total_atual = carteira["Valor atual"].sum() if not carteira.empty else 0.0

        # --- Passo 1: reserva de emergência vem sempre primeiro ---
        meta_reserva = dados["despesa_mensal"] * meses_reserva
        faltam = max(meta_reserva - dados["reserva_atual"], 0)
        if faltam > 0:
            st.warning(f"**1º passo – Reserva de emergência:** meta de {formatar_reais(meta_reserva)} "
                       f"({meses_reserva} meses de despesas). Faltam **{formatar_reais(faltam)}**. "
                       "Costuma-se manter essa reserva em aplicações com liquidez diária e baixo risco "
                       "(ex.: Tesouro Selic ou CDB com liquidez diária).")
        else:
            st.success("✅ Reserva de emergência completa! Pode focar nos demais objetivos.")

        # --- Passo 2: comparar carteira atual com a alocação ideal ---
        ideal = ALOCACAO_POR_PERFIL[perfil_usado]
        atual_por_classe = (carteira.groupby("Classe")["Valor atual"].sum().to_dict()
                            if not carteira.empty else {})
        # Base de cálculo: patrimônio atual + um aporte mensal
        base = total_atual + dados["aporte_mensal"]

        linhas = []
        for classe in CLASSES:
            valor_atual = atual_por_classe.get(classe, 0.0)
            pct_atual = valor_atual / total_atual * 100 if total_atual else 0.0
            pct_ideal = ideal[classe]
            valor_ideal = base * pct_ideal / 100
            linhas.append({
                "Classe": classe,
                "Atual %": round(pct_atual, 1),
                "Ideal %": pct_ideal,
                "Diferença (R$)": round(valor_ideal - valor_atual, 2),
            })
        comparativo = pd.DataFrame(linhas)

        figura = px.bar(comparativo.melt(id_vars="Classe", value_vars=["Atual %", "Ideal %"]),
                        x="Classe", y="value", color="variable", barmode="group",
                        labels={"value": "% da carteira", "variable": ""})
        st.plotly_chart(figura, width="stretch")
        st.dataframe(comparativo, width="stretch", hide_index=True)

        # --- Passo 3: dicas em português claro ---
        st.subheader("💡 Sugestões")
        # Direciona o aporte do mês às classes mais "abaixo do ideal"
        abaixo = comparativo[comparativo["Diferença (R$)"] > 0].sort_values("Diferença (R$)", ascending=False)
        if dados["aporte_mensal"] > 0 and not abaixo.empty:
            destino = ", ".join(abaixo["Classe"].head(2))
            st.write(f"• Seu aporte de {formatar_reais(dados['aporte_mensal'])} pode ir, em prioridade, "
                     f"para: **{destino}** (as mais abaixo do ideal).")
        # Alerta de concentração: um ativo com mais de 40% do total
        if not carteira.empty and total_atual > 0:
            maior = carteira.loc[carteira["Valor atual"].idxmax()]
            if maior["Valor atual"] / total_atual > 0.40:
                st.write(f"• ⚠️ **{maior['Ativo']}** representa mais de 40% da carteira. "
                         "Concentração alta aumenta o risco; considere diversificar.")
        # Contexto de juros
        if cdi is not None and ipca is not None:
            real = cdi - ipca
            if real > 5 and perfil_usado != "Arrojado":
                st.write(f"• Com CDI em {cdi:.2f}% e IPCA em {ipca:.2f}%, a renda fixa está pagando bem acima da inflação.")
            elif real < 3:
                st.write("• O juro real está mais baixo; vale olhar com atenção ativos ligados à inflação (IPCA+) e diversificação.")
        if dados["renda_mensal"] > 0:
            taxa_poupanca = dados["aporte_mensal"] / dados["renda_mensal"] * 100
            st.write(f"• Você investe **{taxa_poupanca:.0f}%** da renda. Uma referência comum é buscar algo entre 10% e 20%.")

    # ---------------- ABA PROJEÇÕES ----------------
    with aba_projecao:
        st.subheader("Quanto seu patrimônio pode crescer?")
        # Retorno médio ponderado da carteira IDEAL do perfil escolhido
        taxa = sum(ideal[c] / 100 * retorno_esperado_anual(c, cdi_uso, ipca_uso) for c in CLASSES)
        carteira = montar_carteira(dados["carteira"])
        inicial = carteira["Valor atual"].sum() if not carteira.empty else 0.0

        taxa = st.slider("Retorno anual esperado (%)", 0.0, 30.0, float(round(taxa, 1)), 0.5,
                         help="Começa com uma estimativa baseada no CDI atual e no seu perfil. Mude à vontade.")
        anos = dados["horizonte_anos"]

        cenarios = {}
        for nome, ajuste in [("Pessimista", -3), ("Base", 0), ("Otimista", 3)]:
            serie = projetar_patrimonio(inicial, dados["aporte_mensal"], max(taxa + ajuste, 0), anos)
            cenarios[nome] = serie["Patrimônio"]
        tabela = pd.DataFrame(cenarios)
        tabela["Anos"] = [m / 12 for m in range(len(tabela))]
        figura = px.line(tabela, x="Anos", y=["Pessimista", "Base", "Otimista"],
                         labels={"value": "Patrimônio (R$)", "variable": "Cenário"})
        st.plotly_chart(figura, width="stretch")

        total_aportado = inicial + dados["aporte_mensal"] * anos * 12
        c1, c2, c3 = st.columns(3)
        c1.metric("Total que você terá aportado", formatar_reais(total_aportado))
        c2.metric(f"Cenário base em {anos} anos", formatar_reais(tabela["Base"].iloc[-1]))
        c3.metric("Ganho com juros (base)", formatar_reais(tabela["Base"].iloc[-1] - total_aportado))
        st.caption("Projeções são hipóteses; o retorno real pode ser muito diferente (inclusive negativo).")


# Aplica a atualização automática: se ativada, o painel se reexecuta sozinho
if atualizar_auto:
    painel_com_refresh = st.fragment(run_every=f"{intervalo}s")(painel_principal)
else:
    painel_com_refresh = st.fragment(painel_principal)
painel_com_refresh()