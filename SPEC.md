# SPEC — Bot de Monitoramento de Taxa do Tesouro Renda+ 2065

> Documento de especificação para implementação. O objetivo é descrever **o que**
> construir e **como** desenhar, com contratos, schema e regras de negócio bem
> definidos. A implementação fica a cargo do Claude Code. Linguagem: **Python**.

---

## 1. Objetivo

Monitorar a taxa do **Tesouro Renda+ Aposentadoria Extra 2065** durante o pregão e
notificar o usuário via **Telegram** quando houver mudança relevante, segundo o modo
de alerta configurado. O bot também responde a comandos interativos e permite
visualizar o histórico de taxas como gráfico.

- **Métrica principal:** taxa de **compra** (investimento), em % a.a.
- **Métrica secundária:** taxa de **resgate** (venda) — sempre exibida junto quando a
  fonte fornecer.
- **Canal:** Telegram (push instantâneo, long polling).
- **Hospedagem:** VPS própria, como daemon `systemd`.

---

## 2. Requisitos funcionais

1. Coletar periodicamente a taxa do título alvo durante o horário de mercado.
2. Suportar múltiplas fontes de dados com fallback automático e toggle por config.
3. Disparar alertas conforme o modo ativo: `sempre`, `threshold` ou `delta`.
4. Enviar um **resumo diário** no fechamento, independente do modo ativo.
5. Persistir histórico de leituras para consulta posterior.
6. Responder a comandos do Telegram para consulta e configuração em runtime
   (sem precisar reiniciar/editar código).
7. Renderizar o histórico como gráfico (PNG) sob demanda.
8. Detectar e notificar falha do próprio bot (dead-man's switch).

---

## 3. Requisitos não-funcionais

- **Latência:** alerta o mais próximo possível do tempo real. Como não há push/websocket
  do Tesouro, o limite é o intervalo de polling (30–60s durante o pregão).
- **Robustez:** falha de fonte é caso esperado, não exceção. Backoff e fallback.
- **Segurança:** segredos (token, chat_id) fora do código, em env vars com permissão
  restrita.
- **Observabilidade:** logs estruturados no journald; heartbeat/health detectável.
- **Extensibilidade:** trocar fonte, adicionar título ou adicionar canal (ex.: email no
  futuro) deve custar pouco — daí as abstrações da seção 4.

---

## 4. Arquitetura

Duas abstrações centrais. O resto do sistema depende das interfaces, nunca das
implementações concretas.

### 4.1 `RateSource` (interface)

Responsável por buscar a taxa de uma fonte específica.

```python
class RateSource(Protocol):
    name: str  # "oficial" | "brapi" | "mock"
    def get_rate(self, titulo: TituloRef) -> RateReading: ...
```

`RateReading` (dataclass) deve conter, no mínimo:

| Campo            | Tipo      | Observação                                  |
|------------------|-----------|---------------------------------------------|
| `titulo`         | str       | nome canônico do título                     |
| `taxa_compra`    | float     | % a.a. (principal)                          |
| `taxa_resgate`   | float?    | % a.a. (None se a fonte não fornecer)       |
| `pu_compra`      | float?    | preço unitário de investimento              |
| `pu_resgate`     | float?    | preço unitário de resgate                   |
| `mercado_aberto` | bool      | derivado do status da fonte                 |
| `timestamp_fonte`| datetime  | `respDtTm` ou equivalente da fonte          |
| `fonte`          | str       | nome da fonte que produziu a leitura        |

Implementações concretas: `OfficialSource`, `BrapiSource`, `MockSource` (para testes).

### 4.2 `Notifier` (interface)

```python
class Notifier(Protocol):
    def send_text(self, msg: str) -> None: ...
    def send_photo(self, png_bytes: bytes, caption: str | None = None) -> None: ...
```

Implementação concreta: `TelegramNotifier`. A interface deixa a porta aberta para um
`EmailNotifier` futuro sem refatorar o core.

### 4.3 Orquestração de fontes (fallback + toggle)

A config define uma **lista ordenada** de fontes. O orquestrador tenta na ordem; cai
para a próxima em caso de timeout, erro HTTP, payload inválido **ou dado estagnado**
(ver 7.3). Trocar a ordem ou desligar uma fonte = editar a lista.

```python
SOURCES_ORDER = ["oficial", "brapi"]  # toggle: basta reordenar/remover
```

> A fonte oficial é a fonte da verdade (atualização quase em tempo real). A brapi tem
> cache de servidor de alguns minutos, então o fallback pode entregar dado levemente
> atrasado — por isso toda mensagem deve indicar **qual fonte** gerou o dado.

---

## 5. Fontes de dados

### 5.1 Oficial (principal)

- **URL:** `https://www.tesourodireto.com.br/json/br/com/b3/tesourodireto/service/api/treasurybondsinfo.json`
- Sem autenticação. JSON consumido pelo próprio site do Tesouro.
- **Atenção:** endpoint não-documentado, historicamente sujeito a 404 intermitente.
  Tratar indisponibilidade como caso normal → fallback.
- **Passo 0 do build:** capturar um payload real durante o pregão e salvá-lo como
  fixture (`tests/fixtures/oficial_sample.json`). Confirmar os nomes de campo abaixo
  contra o JSON real antes de escrever o parser.

Estrutura esperada (a **confirmar** no payload real):

```
response.TrsrBdTradgList[].TrsrBd:
  nm              -> nome do título ("Tesouro Renda+ Aposentadoria Extra 2065")
  mtrtyDt         -> data de vencimento (usar o ano p/ matching: 2065)
  anlInvstmtRate  -> taxa de COMPRA (% a.a.)   [principal]
  anlRedRate      -> taxa de RESGATE (% a.a.)  [secundária]
  untrInvstmtVal  -> PU de compra
  untrRedVal      -> PU de resgate
response.<bloco de status de mercado>  -> aberto/fechado (confirmar campo: stsCod/sts)
response.respDtTm                      -> timestamp da resposta
```

### 5.2 brapi.dev (fallback)

- **Endpoint:** `https://brapi.dev/api/v2/treasury`
- Slugs estáveis no formato `<nome-do-titulo>-<DDMMAAAA>`.
- **Confirmar** se exige token de API (free tier) e, em caso afirmativo, tratá-lo como
  segredo (env var `BRAPI_TOKEN`).
- Normalizar a resposta para o mesmo `RateReading` da fonte oficial.

### 5.3 Matching do título (robusto)

Não casar por string exata. Casar por **tipo ("Renda+") + ano de vencimento (2065)**,
pois a grafia do nome varia entre fontes. Centralizar isso em `TituloRef` para
permitir adicionar outros títulos depois sem tocar no core:

```python
@dataclass
class TituloRef:
    apelido: str          # "renda_mais_2065"
    tipo: str             # "Renda+"
    ano_vencimento: int   # 2065
```

`TITULOS_MONITORADOS` é uma lista na config (hoje só o 2065, mas já generalizado).

---

## 6. Modelo de dados (SQLite)

Banco único `bot.db`. Tabelas:

### `readings` — toda leitura coletada
```sql
CREATE TABLE readings (
  id            INTEGER PRIMARY KEY,
  titulo        TEXT NOT NULL,
  taxa_compra   REAL NOT NULL,
  taxa_resgate  REAL,
  pu_compra     REAL,
  pu_resgate    REAL,
  fonte         TEXT NOT NULL,
  mercado_aberto INTEGER NOT NULL,
  ts_fonte      TEXT,             -- timestamp da fonte
  ts_coleta     TEXT NOT NULL     -- timestamp local da coleta (UTC ISO)
);
CREATE INDEX idx_readings_titulo_ts ON readings (titulo, ts_coleta);
```

### `config` — estado mutável via comandos (key-value)
```sql
CREATE TABLE config (
  chave TEXT PRIMARY KEY,
  valor TEXT NOT NULL
);
-- ex.: modo=threshold, alvo=7.05, alvo_direcao=acima,
--      delta_bps=5, pausado=0, silencio=22:00-08:00
```

### `alert_state` — estado de armar/desarmar por título+modo
```sql
CREATE TABLE alert_state (
  titulo        TEXT NOT NULL,
  ultima_taxa_alertada REAL,
  armado        INTEGER NOT NULL DEFAULT 1,  -- p/ edge-trigger do threshold
  ultimo_alerta_ts TEXT,
  PRIMARY KEY (titulo)
);
```

### Retenção
- `readings` raw: manter **N dias** (config `retencao_dias`, default 30), depois podar.
- Opcional: agregar leituras antigas em resumo diário permanente antes de podar
  (`daily_summary`: data, abertura, máx, mín, fechamento). Mantém histórico de longo
  prazo barato sem inflar o banco.

---

## 7. Lógica de monitoramento

### 7.1 Horário de mercado
- Pollar **apenas** em horário de pregão (~9h30–18h, dia útil). Fora disso, não pollar
  (ou pollar muito esparso só pra manter o `/taxa` minimamente atual).
- **Calendário de feriados B3:** não pollar em feriado. Embutir a lista de feriados
  (ou uma lib como `workalendar`/`holidays` com calendário B3/BR) e validar antes de
  cada ciclo. Sem isso, há risco de falso alerta de "taxa parada".

### 7.2 Intervalo
- Default `poll_interval_seg = 45` (configurável). 30–60s é o sweet spot.
- Definir `User-Agent` próprio nas requisições; não martelar o endpoint.

### 7.3 Detecção de dado estagnado
- Se `ts_fonte`/taxa não avançam entre polls **quando o mercado deveria estar aberto**,
  tratar como falha *soft* → tentar próxima fonte. Evita o bot ficar cego achando que a
  taxa está apenas estável.

### 7.4 Timezone
- `America/Sao_Paulo` em tudo que envolve horário de mercado, feriado e silêncio.
  (Brasil não tem horário de verão desde 2019; ainda assim, TZ explícita.)
- Persistir timestamps em UTC ISO; converter só na exibição.

---

## 8. Modos de alerta

Selecionáveis por comando. Sempre que um alerta dispara, a mensagem traz o pacote
completo (ver seção 9).

### 8.1 `sempre`
Notifica a cada mudança de taxa de compra. **Atenção:** durante o pregão isso gera
muitas mensagens (a taxa flutua continuamente). Útil para observar um dia específico,
não para deixar ligado permanentemente.

### 8.2 `threshold` (alvo)
"Avise quando a taxa de compra cruzar `alvo`."
- **Direção configurável:** `acima` (default — entrada melhor) ou `abaixo`.
- **Edge-triggered:** dispara no **cruzamento**, não a cada poll enquanto está além do
  alvo. Usa `alert_state.armado`: desarma após disparar, **re-arma** quando a taxa volta
  para o outro lado do alvo.
- **Histerese:** margem de re-arme de ~2–3 bps (config `histerese_bps`) para não
  tremular no limiar.

### 8.3 `delta`
"Avise se a taxa de compra mexer mais de `delta_bps` desde o último alerta."
- Compara contra `ultima_taxa_alertada`, não contra a leitura anterior.
- Cooldown configurável para não disparar em rajada.

### 8.4 `resumo_diario` (sempre ativo, em paralelo)
No fechamento do pregão, envia: abertura, máx, mín, fechamento e variação do dia
(em bps e %). Zero spam; serve de baseline mesmo sem alvo definido.

---

## 9. Conteúdo do alerta

Toda notificação de mudança deve conter:

- Título.
- Taxa de compra: **anterior → nova**, com variação em **bps e %**.
- Taxa de resgate (se disponível na fonte).
- PU de compra (e de resgate, se disponível).
- Estado do mercado (aberto/fechado).
- **Fonte** que gerou o dado (oficial/brapi) + timestamp.

> **Armadilha do Telegram:** no MarkdownV2, caracteres como `.`, `-`, `(`, `+` precisam
> de escape, ou a mensagem falha silenciosamente. Usar escaping cuidadoso **ou** enviar
> em texto plano. Não usar HTML/Markdown sem tratar isso.

---

## 10. Comandos do Telegram (long polling)

Long polling (`getUpdates`) — não exige endpoint HTTPS público nem certificado.

| Comando                  | Ação                                                            |
|--------------------------|-----------------------------------------------------------------|
| `/taxa`                  | Taxa atual sob demanda (compra + resgate + PU + fonte + ts)     |
| `/modo sempre\|threshold\|delta` | Troca o modo de alerta                                 |
| `/alvo <valor> [acima\|abaixo]` | Define o threshold e a direção                          |
| `/delta <bps>`           | Define a sensibilidade do modo delta                            |
| `/status`                | Config atual + saúde do bot + último fetch ok + fonte em uso     |
| `/historico [dias]`      | Gráfico PNG do histórico (ver seção 11). Default: 1 dia          |
| `/export [dias]`         | (Opcional) Dump CSV das leituras                                |
| `/pausar` / `/retomar`   | Muta/desmuta alertas sem matar o serviço                        |
| `/silencio HH:MM-HH:MM`  | Quiet hours (relevante p/ alertas de erro)                      |
| `/test`                  | Dispara um alerta fake — valida o cano do Telegram ponta a ponta |
| `/help`                  | Lista os comandos                                               |

- **Autorização:** o bot só responde ao `chat_id` autorizado (config). Ignorar o resto.

---

## 11. Visualização de histórico (healthcheck manual)

Objetivo: bater o olho e confirmar que o bot está amostrando corretamente e ver a
tendência da taxa.

- Comando `/historico [dias]` (default 1).
- Consulta `readings` do período, **downsample para buckets de ~5 min** para manter o
  gráfico legível (média do bucket, ou último valor do bucket).
- Renderiza com **matplotlib em backend `Agg`** (headless, sem GUI na VPS), salva em
  `BytesIO` e envia via `send_photo`.
- Plotar **taxa de compra** (linha sólida) e, quando houver dados, **taxa de resgate**
  (linha tracejada). Eixo X = tempo; eixo Y = % a.a.
- Caption com período, mín/máx do período e fonte predominante.
- `/export` (opcional) entrega CSV cru para análise mais profunda fora do Telegram.

---

## 12. Confiabilidade & observabilidade

- **Dead-man's switch:** se **todas** as fontes falharem por `N` ciclos consecutivos
  (config `max_falhas_consecutivas`), enviar um alerta avisando que o **bot** está cego.
  Silêncio não pode ser ambíguo ("taxa estável" vs "bot morto").
- **Throttle de erros:** o dead-man switch e erros em geral têm rate-limit próprio
  (1 aviso + cooldown), para não inundar o chat.
- **Backoff exponencial** em falha de rede antes de retentar a mesma fonte.
- **Logs:** estruturados, nível configurável, saída para journald.
- **Heartbeat opcional:** `/status` deve reportar "último fetch OK há X min".

---

## 13. Configuração & segredos

- Segredos em **env vars** (`.env` carregado via `python-dotenv`, ou `EnvironmentFile`
  do systemd com `chmod 600`):
  - `TELEGRAM_BOT_TOKEN`
  - `TELEGRAM_CHAT_ID`
  - `BRAPI_TOKEN` (se necessário)
- Config operacional (modo, alvo, intervalos, retenção) vive na tabela `config` do
  SQLite, mutável por comando. Defaults num `config.example`/constantes no código.
- **Nunca** hardcodar token/chat_id.

---

## 14. Estrutura de projeto sugerida

```
renda_bot/
├── SPEC.md
├── pyproject.toml / requirements.txt
├── .env.example
├── renda_bot/
│   ├── __init__.py
│   ├── config.py          # leitura de env + defaults
│   ├── models.py          # RateReading, TituloRef, dataclasses
│   ├── sources/
│   │   ├── base.py        # RateSource (Protocol)
│   │   ├── oficial.py
│   │   ├── brapi.py
│   │   └── mock.py
│   ├── orchestrator.py    # fallback + toggle + detecção de estagnado
│   ├── storage.py         # SQLite: readings, config, alert_state, retenção
│   ├── alerts.py          # lógica dos modos (sempre/threshold/delta) + resumo
│   ├── notifier/
│   │   ├── base.py        # Notifier (Protocol)
│   │   └── telegram.py
│   ├── commands.py        # handlers do long polling
│   ├── charts.py          # /historico -> PNG (matplotlib Agg)
│   ├── market.py          # horário de pregão + feriados B3 + TZ
│   ├── health.py          # dead-man switch + throttle de erro
│   └── main.py            # daemon: scheduler de poll + loop de comandos
├── tests/
│   ├── fixtures/oficial_sample.json
│   └── ...
└── deploy/
    └── renda-bot.service  # unit systemd
```

---

## 15. Ordem de build sugerida

1. Capturar fixture do JSON oficial + confirmar schema (seção 5.1).
2. `models.py` + `RateSource` + `OfficialSource` + `BrapiSource` + orquestrador com
   fallback e toggle (5, 4.3).
3. `Notifier` + `TelegramNotifier` + `/test` funcionando ponta a ponta (4.2, 10).
4. `storage.py` (SQLite) + modo `delta` (já exige dedupe/estado).
5. Modo `threshold` com edge-trigger + histerese (8.2).
6. Handler de comandos completo (10).
7. `/historico` com gráfico (11).
8. Dead-man switch + resumo diário + horário de mercado/feriados (7, 8.4, 12).
9. systemd + segredos + hardening (13).

---

## 16. Pontos a confirmar / armadilhas conhecidas

- [ ] Confirmar nomes de campo do JSON oficial contra payload real (não confiar de cor).
- [ ] Confirmar se a brapi exige token e qual o slug exato do Renda+ 2065.
- [ ] Escaping MarkdownV2 do Telegram (ou usar texto plano).
- [ ] Calendário de feriados B3 — usar lib confiável e validar.
- [ ] matplotlib em backend `Agg` (headless) na VPS.
- [ ] Garantir que o bot só responde ao `chat_id` autorizado.
- [ ] Retenção/poda do `readings` para o banco não crescer indefinidamente.
- [ ] Edge-trigger com histerese no threshold (evitar spam no limiar).

---

## 17. Deploy (systemd)

Daemon de longa duração (long polling + scheduler interno). Esboço da unit:

```ini
[Unit]
Description=Bot de monitoramento Tesouro Renda+ 2065
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=rendabot
WorkingDirectory=/opt/renda_bot
EnvironmentFile=/opt/renda_bot/.env
ExecStart=/opt/renda_bot/.venv/bin/python -m renda_bot.main
Restart=on-failure
RestartSec=10

[Install]
WantedBy=multi-user.target
```

- Logs via journald (`journalctl -u renda-bot`).
- `.env` com `chmod 600`, dono `rendabot`.
