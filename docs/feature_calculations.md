# Feature Calculations Reference

All features are computed in `src/features/compute.py` from raw OHLCV candle data.
The pipeline ingests 15-minute BTC/USDT candles from Binance, then derives 15 features
split across three categories.

---

## Data Sources

| Source | API Endpoint | Data Provided | Auth Required |
|--------|-------------|---------------|---------------|
| Binance | `GET /api/v3/klines` | OHLCV candles (open, high, low, close, volume) at 15-min intervals | No (public) |
| Alternative.me | `GET /fng/?limit=N` | Daily Fear & Greed Index (0-100) | No |
| CoinGecko | `GET /api/v3/coins/bitcoin/market_chart` | Historical BTC market cap (daily) | No (free tier) |
| CoinGecko | `GET /api/v3/global` | Current BTC dominance, total market cap | No (free tier) |

---

## Binance-Derived Features (12)

These features are computed from the raw OHLCV candles. All rolling windows use
`min_periods` equal to the window size, so the first 30 rows are NaN (warm-up) and
get dropped before training.

### Volatility Features

| Feature | Formula | Intuition |
|---------|---------|-----------|
| `volatility_10m` | `std(pct_change(close), window=10)` | Short-term price instability. High values = rapid price swings in the last 10 candles. |
| `volatility_30m` | `std(pct_change(close), window=30)` | Longer-term volatility baseline. Smoother than 10m. |
| `volatility_ratio` | `volatility_10m / volatility_30m` | Regime detector. Ratio > 1 = short-term vol exceeding long-term (breakout signal). Ratio < 1 = calming market. |

### Momentum Features

| Feature | Formula | Intuition |
|---------|---------|-----------|
| `rsi_14` | `100 - (100 / (1 + EWM(gain,14) / EWM(loss,14)))` | Relative Strength Index. RSI > 70 = overbought (reversal risk). RSI < 30 = oversold (bounce potential). Uses Wilder smoothing (EWM span=14). |

### Volume Features

| Feature | Formula | Intuition |
|---------|---------|-----------|
| `volume_spike` | `volume / rolling_mean(volume, 30)` | Detects abnormal trading activity. Value of 5 = current volume is 5x the 30-candle average. Often precedes big moves. |
| `volume_trend` | `rolling_mean(volume, 10) / rolling_mean(volume, 30)` | Short vs long-term volume trend. Values > 1 = increasing participation. Values < 1 = declining interest. |

Note: CoinGecko free tier returns volume=0. When using CoinGecko data, volume features
are filled with 1.0 (neutral). Binance provides real volume data.

### Price Structure Features

| Feature | Formula | Intuition |
|---------|---------|-----------|
| `price_range_30m` | `rolling_max(high, 30) - rolling_min(low, 30)` | Dollar width of the 30-candle price channel. Wide range = high volatility environment. |
| `sma_10_vs_sma_30` | `SMA(close, 10) / SMA(close, 30)` | Trend direction. Values > 1 = short-term price above long-term (uptrend). Values < 1 = downtrend. |
| `max_drawdown_30m` | `(close - rolling_max(close, 30)) / rolling_max(close, 30)` | How far price has fallen from 30-candle high. Always <= 0. Values near 0 = at highs. Values like -0.03 = 3% drawdown. |
| `candle_body_avg` | `rolling_mean(abs(close - open), 10)` | Average candle body size over 10 candles. Large bodies = strong directional moves. Small bodies = indecision. |

### Temporal Features

| Feature | Formula | Intuition |
|---------|---------|-----------|
| `hour_of_day` | `timestamp.hour` (0-23) | Captures intraday patterns. Crypto is 24/7 but volatility clusters around US/Asia market hours. |
| `day_of_week` | `timestamp.dayofweek` (0=Mon, 6=Sun) | Captures weekly patterns. Weekends often have lower volume and different volatility profiles. |

---

## Sentiment & Market Features (3) - External APIs

These features capture market-wide conditions that can't be derived from BTC price alone.
They are daily-granularity values mapped to each 15-min candle by date.

| Feature | Source | Formula | Intuition |
|---------|--------|---------|-----------|
| `fear_greed` | Alternative.me FNG API | Daily index value (0-100) mapped to candle date, forward-filled | Market sentiment. 0-25 = Extreme Fear (potential buying opportunity). 75-100 = Extreme Greed (potential correction ahead). |
| `market_cap_change_24h` | CoinGecko market_chart | `pct_change(daily_btc_market_cap) * 100` | Daily BTC market cap momentum. Positive = capital flowing in. Negative = capital flowing out. |
| `btc_dominance` | CoinGecko global + market_chart | Estimated from BTC market cap trajectory anchored to current dominance | BTC's share of total crypto market. Rising dominance = flight to safety. Falling = altcoin season / risk-on. |

### Fallback Values

External APIs can fail. When they do, the pipeline fills with neutral values:

| Feature | Fallback | Reasoning |
|---------|----------|-----------|
| `fear_greed` | 50.0 | Neutral sentiment (neither fear nor greed) |
| `market_cap_change_24h` | 0.0 | No change (neutral) |
| `btc_dominance` | 55.0 | Approximate historical average |

---

## Label Calculation

Defined in `src/features/labels.py`. This is a **forward-looking** label (the model predicts future volatility).

```
Label at row T = 1 (VOLATILE) if max price swing in T+1..T+30 > 2%
                 0 (CALM) otherwise

Price swing = (max(close[T+1:T+31]) - min(close[T+1:T+31])) / close[T]
Threshold = 0.02 (2%)
```

- Forward window: 30 candles = 7.5 hours at 15-min interval
- Last 30 rows are always dropped (incomplete forward window)
- Row T is NOT included in its own label (prevents look-ahead bias)

---

## Data Flow

```
Binance API ──> raw OHLCV (S3) ──> compute_features() ──> label_volatility()
                                        │                        │
                                   12 features              adds "label"
                                        │                        │
External APIs ──> 3 sentiment ──────────┘                        │
                  features                                       v
                                                    Feast offline store (S3 Parquet)
                                                            │
                                                    feast materialize
                                                            │
                                                    Redis online store
                                                      (serving path)
```

---

## Warm-Up Period

The first 30 rows of any batch will have NaN features because rolling windows
need 30 data points to produce a value. These rows are dropped by `dropna()`
in `scripts/compute_features.py` before writing to the Feast offline store.

For a 90-day backfill at 15-min intervals: ~8,640 raw candles - 30 warm-up - 30 label
window = ~8,580 usable training rows.
