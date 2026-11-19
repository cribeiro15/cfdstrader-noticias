# CFDsTrader · Bot de noticias

Publica automáticamente en el canal **#información** del Discord CFDsTrader:

| Fuente | Qué publica | Máx. por ronda |
|---|---|---|
| Bloomberg | Noticias de mercados | 4 |
| Wall Street Journal | Noticias de mercados | 4 |
| Financial Times | Noticias de mercados | 4 |
| Yahoo Finance | Noticias | 4 |
| Investing.com | Noticias de bolsa | 4 |
| TradingView | Ideas de traders populares | 2 |
| ForexFactory | Calendario del día (solo impacto alto, hora de Madrid), a partir de las 7:00 | 1 al día |

Se ejecuta gratis en GitHub Actions cada 15 minutos. No repite noticias (guarda el historial en `seen.json`).
La primera vez solo publica la última noticia de cada fuente, para no llenar el canal.

## Puesta en marcha (una sola vez)

1. **Webhook de Discord**: en Discord → ⚙️ de #información → *Integraciones* → *Webhooks* → *Nuevo webhook* → *Copiar URL del webhook*.
2. **Secreto en GitHub**: en este repositorio → *Settings* → *Secrets and variables* → *Actions* → *New repository secret*.
   - Name: `DISCORD_WEBHOOK_URL`
   - Secret: pega la URL del webhook.
3. **Primera ejecución**: pestaña *Actions* → *Noticias CFDsTrader* → *Run workflow*.

## Cambiar fuentes

Edita la lista `FEEDS` en `bot.py` (nombre, URL del RSS, color, máximo por ronda).
Si una fuente falla, el registro de *Actions* lo indica con ✗ y el resto sigue funcionando.

> Nota: GitHub pausa los workflows programados si el repositorio pasa 60 días sin actividad. Si dejan de llegar noticias, entra en *Actions* y pulsa *Enable workflow*.
