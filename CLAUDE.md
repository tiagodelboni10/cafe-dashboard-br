# Cafeza — Cultivar Inteligente

## Sobre o Projeto
Dashboard completo de mercado de cafe (Arabica e Conilon/Robusta) para cafeicultores brasileiros.
O projeto esta evoluindo para se tornar um **site e app comercial** com o nome **Cafeza**.

- **Site ao vivo:** https://tiagodelboni10.github.io/cafe-dashboard-br/dashboard.html
- **API (Cafeza AI):** https://cafe-dashboard-br.vercel.app/api/chat
- **Repo:** https://github.com/tiagodelboni10/cafe-dashboard-br

## Stack
- **Frontend:** HTML estatico gerado por Python (`src/html_dashboard.py`)
- **Backend AI:** Vercel serverless function (`api/chat.py`) com OpenAI GPT-4o-mini
- **Deploy dashboard:** GitHub Pages via GitHub Actions (a cada 30min, 06h-20h BRT, seg-sab)
- **Deploy API:** Vercel (auto-deploy no push)
- **Dados:** Yahoo Finance, Barchart, paineldocafe API, Noticias Agricolas, Google News RSS, Open-Meteo

## Arquitetura
- `main.py` — entry point, chama `generate_html_dashboard()`
- `src/config.py` — feeds RSS, tickers, keywords de sentimento
- `src/market_data.py` — precos futuros (yfinance + scraping Barchart)
- `src/macro_data.py` — USD/BRL, clima, estoques ICE, COT, fertilizantes, paineldocafe, CEPEA, conhecimento, marketplace
- `src/news_fetcher.py` — noticias via RSS (Reuters, Bloomberg, etc.)
- `src/analyzer.py` — sentimento + analise tecnica + recomendacao
- `src/html_dashboard.py` — gera o HTML completo com graficos Plotly
- `api/chat.py` — Cafeza AI (serverless Vercel + OpenAI)

## Fluxo de Deploy
1. Alterar codigo
2. `python main.py` para testar localmente
3. `git add ... && git commit && git push`
4. `gh workflow run 247440350 --repo tiagodelboni10/cafe-dashboard-br --ref master` para deploy GitHub Pages
5. Vercel faz auto-deploy no push

## Horario
- Sempre usar **BRT (UTC-3)** para timestamps no dashboard
- GitHub Actions roda em UTC, converter com `timezone(timedelta(hours=-3))`

## Regras
- O irmao do Tiago acompanha o site, entao SEMPRE fazer deploy apos alteracoes
- Nao usar noticias do paineldocafe.com.br (removido), manter apenas precos
- Fontes de noticias: Reuters, Bloomberg, Financial Times, Barchart, Noticias Agricolas, Valor Economico, InfoMoney
- Dashboard e self-contained: um unico HTML com CSS/JS inline
- Tema dark: #0f0f23 body, #1a1a2e cards, #16213e accents, #4fc3f7 headings
- Auto-refresh de 5 minutos no navegador (meta refresh)

## Roadmap de Melhorias (7 dias)

### Dia 1-2: UX e Visual
- [ ] Melhorar responsividade mobile (testar em celular)
- [ ] Adicionar favicon do Cafeza
- [ ] Menu de navegacao rapida (scroll para secoes)
- [ ] Indicador visual de "ultima atualizacao" mais visivel
- [ ] Animacoes suaves nos cards de preco

### Dia 3-4: Dados e Analise
- [ ] Grafico historico de precos do mercado fisico (CEPEA) — salvar dados em JSON
- [ ] Comparativo de precos entre pracas (qual praca paga mais)
- [ ] Alertas de preco (quando ultrapassa limites configurados)
- [ ] Previsao de tendencia com media movel + indicadores
- [ ] Adicionar dados de exportacao brasileira de cafe

### Dia 5-6: Conteudo e Marketplace
- [ ] Expandir guia do cafeicultor com mais topicos (certificacoes, cafe especial, sustentabilidade)
- [ ] Calculadora de custo de producao (inputs: area, produtividade, insumos)
- [ ] Formulario de contato real no marketplace (WhatsApp links)
- [ ] Secao de clima com previsao de 15 dias e alertas de geada
- [ ] Adicionar calendario de eventos do setor (feiras, leiloes)

### Dia 7: Polish e Performance
- [ ] Otimizar tamanho do HTML (lazy load de graficos)
- [ ] Adicionar Open Graph tags para compartilhamento
- [ ] Testar e corrigir erros em todos os data fetchers
- [ ] Garantir fallbacks quando APIs estao fora do ar
- [ ] Revisao geral de conteudo e ortografia
