# rendamais-bot

Bot em Python que monitora a taxa do Tesouro Renda+ Aposentadoria Extra 2065 durante o
pregão e envia alertas via Telegram quando há mudança relevante na taxa.

## Funcionalidades

- Coleta periódica da taxa (compra e resgate) com múltiplas fontes e fallback automático.
- Alertas configuráveis por modo: sempre, threshold ou delta.
- Resumo diário no fechamento do pregão.
- Histórico de leituras persistido em banco local.
- Comandos interativos via Telegram para consulta e configuração em runtime.
- Gráfico de histórico sob demanda.
- Detecção de falha do próprio bot (dead-man's switch).

## Requisitos

- Python 3.13+
- Um bot do Telegram (token) e o chat ID de destino

## Instalação

```bash
git clone git@github.com:vazleo/rendamais-bot.git
cd rendamais-bot
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

## Configuração

Copie o arquivo de exemplo e preencha as variáveis:

```bash
cp .env.example .env
```

| Variável | Descrição |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Token do bot obtido via BotFather |
| `TELEGRAM_CHAT_ID` | ID do chat que receberá os alertas |

## Uso

Iniciar o bot em background:

```bash
./start-bot.sh
```

Os logs ficam em `bot.log`. Para rodar em primeiro plano diretamente:

```bash
python3 -m renda_bot.main
```

## Comandos do Telegram

| Comando | Descrição |
|---|---|
| `/taxa` | Taxa atual |
| `/modo sempre\|threshold\|delta` | Troca o modo de alerta |
| `/alvo <val> [acima\|abaixo]` | Define alvo do modo threshold |
| `/delta <bps>` | Define sensibilidade do modo delta |
| `/status` | Configuração e saúde do bot |
| `/historico [dias]` | Gráfico de histórico |
| `/export [dias]` | Exporta leituras em CSV |
| `/pausar` | Pausa alertas |
| `/retomar` | Reativa alertas |
| `/silencio HH:MM-HH:MM` | Define quiet hours |
| `/test` | Dispara um alerta de teste |
| `/help` | Lista de comandos |

## Estrutura do projeto

```
renda_bot/
  main.py          ponto de entrada
  orchestrator.py  laço principal de coleta e alertas
  commands.py      comandos do Telegram
  alerts.py        regras de disparo de alerta
  market.py        janela e calendário de pregão
  storage.py        persistência do histórico
  charts.py        geração de gráficos
  health.py        dead-man's switch
  config.py        configuração em runtime
  sources/         fontes de dados da taxa (com fallback)
  notifier/        canais de notificação (Telegram)
deploy/
  renda-bot.service  unit systemd para hospedagem em VPS
tests/
SPEC.md            especificação funcional e técnica completa
```

## Deploy

O serviço foi desenhado para rodar como daemon `systemd` em uma VPS. Veja
`deploy/renda-bot.service`.

## Testes

```bash
pytest
```
