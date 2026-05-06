# 777moneymaker — Instrukcja użytkowania

## Spis treści
1. [Co to jest?](#co-to-jest)
2. [Architektura systemu](#architektura-systemu)
3. [Konfiguracja brokera](#konfiguracja-brokera)
4. [Uruchomienie programu](#uruchomienie-programu)
5. [Zakładki aplikacji](#zakładki-aplikacji)
6. [Jak działa AI?](#jak-działa-ai)
7. [BrainBot — autonomiczny skaner rynku](#brainbot--autonomiczny-skaner-rynku)
8. [System samouczenia się](#system-samouczenia-się)
9. [Zarządzanie ryzykiem](#zarządzanie-ryzykiem)
10. [Short selling](#short-selling)
11. [Bezpieczeństwo kluczy API](#bezpieczeństwo-kluczy-api)
12. [Monitorowanie i logi](#monitorowanie-i-logi)
13. [Rozwiązywanie problemów](#rozwiązywanie-problemów)

---

## Co to jest?

**777moneymaker** to system automatycznego tradingu z interfejsem graficznym, który:
- Pobiera dane rynkowe z Alpaca (IEX feed) z fallbackiem do Yahoo Finance
- Co minutę automatycznie pobiera newsy z **Finnhub API** — ogólnorynkowe (general/forex/merger) + firmowe dla każdego symbolu — wraz z **pełną treścią artykułów**
- Wysyła dane do **lokalnego modelu AI** (Ollama) — **bez opłat za API, działa offline**
- AI analizuje: techniczne wskaźniki + newsy z treścią + profil własnych wyników i podejmuje decyzję: **KUP / SPRZEDAJ / CZEKAJ**
- **BrainBot** skanuje cały rynek (~12 000 symboli) co godzinę i rekomenduje najlepsze kandydaty
- Bot **uczy się na własnych decyzjach** — oblicza win rate, kalibruje confidence i dostosowuje progi dla każdego symbolu osobno
- System automatycznie składa zlecenia przez **Alpaca Markets API** — obsługuje zarówno long jak i **short**
- Zarządza ryzykiem (stop-loss, take-profit, egzekwowanie SL/TP, dzienny limit strat)
- GUI odświeża dane z Alpaca co 30 sekund — nawet gdy bot jest zatrzymany

---

## Architektura systemu

```
777moneymaker/
├── dashboard.py                 ← Punkt wejścia — aplikacja okienkowa (GUI)
├── main.py                      ← Punkt wejścia CLI (trading bez GUI)
├── config.yaml                  ← Konfiguracja (broker, ryzyko, LLM, BrainBot)
├── .env                         ← Klucze API (NIE commitować!)
├── requirements.txt             ← Zależności Python
├── gui/
│   ├── main_window.py           ← Główne okno, zarządza wszystkimi wątkami
│   ├── alpaca_poller.py         ← Tło: konto/pozycje co 30s
│   ├── trading_worker.py        ← Wątek silnika tradingowego (TradingEngine)
│   ├── tab_dashboard.py         ← Zakładka: pulpit
│   ├── tab_chart.py             ← Zakładka: wykresy
│   ├── tab_market.py            ← Zakładka: rynek
│   ├── tab_positions.py         ← Zakładka: pozycje
│   ├── tab_tradebot.py          ← Zakładka: status TradeBota
│   ├── tab_brainbot.py          ← Zakładka: BrainBot (dziennik, log, czat)
│   ├── tab_decisions.py         ← Zakładka: decyzje AI
│   ├── tab_news.py              ← Zakładka: newsy (auto-refresh co minutę)
│   ├── tab_logs.py              ← Zakładka: logi
│   └── tab_settings.py          ← Zakładka: ustawienia (5 podzakładek)
├── modules/
│   ├── market_data.py           ← Pobieranie danych + wskaźniki techniczne
│   ├── finnhub_client.py        ← Klient Finnhub: newsy + pełna treść artykułów
│   ├── news_store.py            ← Zapis i filtrowanie newsów (data/news.jsonl)
│   ├── news_poller.py           ← Wątek: auto-fetch newsów co 60s
│   ├── symbol_brain.py          ← Scoring symboli, watchlista, persistencja
│   ├── brain_scanner.py         ← BrainBot: hourly refresh + LLM skan top 100
│   ├── brain_journal.py         ← Pamięć BrainBota: rekomendacje, notatki, czat
│   ├── symbol_learner.py        ← Samouczenie: profil wyników per symbol
│   ├── llm_analyzer.py          ← Komunikacja z Ollama, budowanie promptów
│   ├── risk_manager.py          ← Zarządzanie ryzykiem, wielkość pozycji
│   ├── trading_engine.py        ← Główny silnik decyzyjny
│   ├── trade_logger.py          ← Logowanie transakcji i decyzji AI
│   └── brokers/
│       ├── base_broker.py       ← Interfejs abstrakcyjny
│       └── alpaca_broker.py     ← Integracja z Alpaca (IEX feed, paper + live)
├── logs/
│   └── last_logs.log            ← Główny log systemu
└── data/
    ├── trades.csv               ← Historia transakcji
    ├── ai_decisions.jsonl       ← Decyzje AI (JSON Lines)
    ├── news.jsonl               ← Newsy z Finnhub z treścią artykułów
    ├── symbol_brain.json        ← Scoring ~12 000 symboli (kompaktowy JSON)
    └── brain_journal.json       ← Rekomendacje i pamięć BrainBota
```

### Przepływ danych między modułami

```
Alpaca API (batch, ~13 callów/h)
        ↓
BrainScanner — hourly refresh wszystkich ~12 000 symboli
        ↓
_rebuild_top_universe() — ranking wg score (bez API)
        ↓
LLM skan top 100 — decyzja BUY/SELL/HOLD
        ↓
BrainJournal.recommended_now — lista max 50 rekomendacji
        ↓
TradingEngine — watchlista max 30 symboli → pełna analiza → zlecenia
```

---

## Konfiguracja brokera

### Alpaca Markets

Jedyny obsługiwany broker. Obsługuje zarówno **paper trading** (wirtualne pieniądze) jak i **live trading** — tryb przełącza się w zakładce **Ustawienia → Broker**, bez edycji plików.

1. Utwórz konto na [alpaca.markets](https://alpaca.markets)
2. Wygeneruj klucze API w panelu Alpaca:
   - Paper trading: panel → "Paper Accounts" → "View" → "API Keys"
   - Live trading: panel → "Live" → "API Keys"
3. Wpisz klucze w aplikacji: **Ustawienia → API → Alpaca API**
4. Kliknij **Zapisz klucze**, następnie **Sprawdź API** — zobaczysz status połączenia i saldo konta

```env
# .env — możesz też wpisać ręcznie
ALPACA_API_KEY=twój_klucz
ALPACA_SECRET_KEY=twój_secret
```

> Tryb paper/live **nie** wymaga zmiany URL ani edycji `.env`. Wystarczy zmienić w Ustawieniach → Broker.

### Finnhub (opcjonalne — newsy dla AI)

1. Utwórz darmowe konto na [finnhub.io](https://finnhub.io)
2. Skopiuj klucz API z panelu
3. Wpisz w aplikacji: **Ustawienia → API → Finnhub API**
4. Kliknij **Zapisz** i **Sprawdź** — test połączenia potwierdzi klucz

Po skonfigurowaniu Finnhub, aplikacja automatycznie co minutę pobiera newsy dla wszystkich symboli — bez żadnej dodatkowej akcji ze strony użytkownika.

Bez Finnhub bot działa normalnie — newsy są po prostu pomijane przez AI.

---

## Uruchomienie programu

Upewnij się, że środowisko wirtualne zostało skonfigurowane (patrz `INSTALACJA.md`).

### Uruchomienie aplikacji

```bash
# Aktywuj venv (jeśli nie jest aktywny)
venv\Scripts\activate     # Windows
source venv/bin/activate  # Linux/macOS

python dashboard.py
```

### Pierwsze uruchomienie

1. Przejdź do zakładki **Ustawienia → Broker** — wybierz tryb (Paper / Live)
2. Przejdź do **Ustawienia → API** — wpisz klucze Alpaca i opcjonalnie Finnhub
3. Wróć na **Dashboard** — dane konta pojawią się automatycznie (poller startuje razem z aplikacją)
4. Kliknij **▶ Start** — TradingBot i BrainBot startują równolegle

> Przy pierwszym uruchomieniu z pustą bazą BrainBot wykona jednorazowy skan inicjalizacyjny (~12 000 symboli, kilkanaście minut). Przy kolejnych startach wczytuje dane z `data/symbol_brain.json` i startuje natychmiast.

---

## Zakładki aplikacji

| Zakładka | Opis |
|----------|------|
| **Dashboard** | Equity, cash, otwarte pozycje, dzienny P&L, ostatnie transakcje, start/stop bota |
| **Wykres** | Interaktywny wykres z candlesticks, wskaźnikami, crosshairem — hover pokazuje OHLCV |
| **Rynek** | Aktualne ceny i sygnały AI; kolumna "Pozycja" pokazuje aktywne longi/shorty |
| **Pozycje** | Lista otwartych pozycji z unrealized P&L i przycisk ↻ Odśwież |
| **TradeBot** | Status bota, aktywna watchlista, parametry cyklu |
| **BrainBot** | Dziennik rekomendacji, log skanera, czat z AI, statystyki |
| **Decisions** | Pełna historia decyzji AI — akcja, confidence, uzasadnienie, sygnały, wpływ newsów |
| **News** | Newsy odświeżane automatycznie co minutę; filtrowanie po symbolu i dacie |
| **Logi** | Podgląd logów na żywo (ostatnie wpisy z `logs/last_logs.log`) |
| **Ustawienia** | 5 podzakładek — każda z osobnym przyciskiem Zapisz |

### Ustawienia — podzakładki

| Podzakładka | Co konfiguruje |
|-------------|----------------|
| **Broker** | Wybór brokera, tryb paper/live |
| **API** | Klucze Alpaca i Finnhub — zapis i test połączenia |
| **AI** | Model Ollama, temperatura, timeout, URL serwera |
| **Risk** | Min. confidence, max pozycje, dzienny stop, wielkość pozycji, SL/TP |
| **Pozostałe** | Interwał pętli bota, poziom logowania |

---

## Jak działa AI?

### Przepływ danych — jeden cykl TradingEngine (co 60 sekund)

```
1. Sprawdź SL/TP dla wszystkich otwartych pozycji → zamknij jeśli trafione
        ↓
2. Pobierz listę symboli z BrainJournal (recommended_now) → watchlista max 30
        ↓
3. Pobierz wszystkie newsy jednym wywołaniem (market + forex + merger + firmowe)
   → równolegle wyciągnij pełną treść artykułów (trafilatura, 8 wątków)
        ↓
4. Dla każdego symbolu z watchlisty:
   a. Pobierz dane OHLCV z Alpaca (IEX) lub Yahoo Finance (fallback)
   b. Oblicz wskaźniki: RSI, MACD, Bollinger Bands, SMA 20/50/200, ATR, Volume
   c. Oblicz wskaźniki tygodniowe: RSI, MACD, SMA 10w/20w/50w, trend
   d. Wylicz Profil Nauki (SymbolLearner) — win rate, kalibracja, wzorzec decyzji
        ↓
5. Zbuduj prompt LLM:
   [Profil Nauki] → [Newsy makro z treścią] → [Newsy firmowe z treścią]
   → [Timeframe tygodniowy] → [Wskaźniki dzienne] → [Historia decyzji]
        ↓
6. Wyślij do Ollama (http://localhost:11434) → lokalny model AI
        ↓
7. LLM zwraca JSON: {action, confidence, stop_loss, take_profit, reasoning, news_impact}
        ↓
8. Risk Manager waliduje sygnał (confidence ≥ 60%, max pozycje, dzienny stop)
        ↓
9. Jeśli OK → złóż zlecenie przez Alpaca API
        ↓
10. Zapisz transakcję do data/trades.csv, decyzję do data/ai_decisions.jsonl
    → przy następnym cyklu SymbolLearner uwzględni tę decyzję w profilu
```

### Przykładowa odpowiedź LLM

```json
{
  "action": "BUY",
  "confidence": 0.74,
  "entry_price": 185.20,
  "stop_loss": 181.50,
  "take_profit": 192.61,
  "reasoning": "AAPL powyżej wszystkich kluczowych SMA. MACD histogram rośnie. RSI=58 — przestrzeń do wzrostu. Reuters: Apple zapowiada nowy produkt (pozytywne). Profil nauki: win rate 68% — utrzymuję aktualną strategię.",
  "key_signals": [
    "Ponad SMA20/50/200 — silny trend wzrostowy",
    "MACD crossover bullish",
    "Bullish news: nowy produkt Apple",
    "Win rate 68% — strategia skuteczna"
  ],
  "news_impact": "bullish"
}
```

---

## BrainBot — autonomiczny skaner rynku

BrainBot działa jako osobny wątek równolegle z TradingEngine. Skanuje cały rynek i dostarcza watchlistę dla TradeBota.

### Trzy warstwy (co godzinę)

```
1. Hourly refresh — wszystkie ~12 000 symboli
   ~13 batch callów API (1000 symboli/request)
   → aktualizuje momentum i volume_ratio w brain
        ↓
2. Rebuild top universe — bez API
   Sortuje ~12 000 symboli wg score → wyłania top 1000
        ↓
3. LLM skan — top 100 symboli
   Pełna analiza: snapshot + newsy + LLM → BUY/SELL/HOLD
   → wyniki do BrainJournal.recommended_now
```

### Co jest w zakładce BrainBot

- **Dziennik rekomendacji** — lista symboli z akcją, confidence i uzasadnieniem
- **Watch later** — symbole z niższym score warte obserwowania
- **Log skanera** — na żywo: który symbol, jaka decyzja, jakie uzasadnienie
- **Czat z AI** — możesz zapytać BrainBota o stan rynku, rekomendacje, zmienić jego fokus

### Czat z BrainBotem

BrainBot odpowiada na pytania po polsku, znając aktualny stan rekomendacji i notatek uczenia. Słowa kluczowe strategii ("skup się na", "unikaj", "ignoruj") są wyciągane i zapisywane jako wskazówki użytkownika — BrainBot uwzględnia je w kolejnych skanach.

Przykłady:
- *"Jakie masz teraz rekomendacje?"* → lista aktualnych BUY/SELL z uzasadnieniem
- *"Skup się na spółkach technologicznych"* → zostanie zapisane jako wskazówka strategiczna
- *"Dlaczego rekomendowałeś CAT?"* → wyjaśnienie na podstawie notatek i ostatnich sygnałów

---

## System samouczenia się

Bot automatycznie uczy się na własnych decyzjach i transakcjach. Dla każdego symbolu `SymbolLearner` oblicza profil nauki wstrzykiwany do każdego promptu LLM.

### Co zawiera profil nauki

- **Liczba i rozkład decyzji** — ile BUY / SELL / HOLD zostało podjętych
- **Win rate** — % transakcji zakończonych zyskiem (na podstawie par BUY→SELL z `trades.csv`)
- **Średni zwrot** — średnia % zmiana ceny na zamkniętych transakcjach
- **Kalibracja confidence** — czy AI z wysoką confidence faktycznie wygrywa częściej?
- **Top sygnały w zyskach** — które `key_signals` towarzyszyły wygranym transakcjom
- **Top sygnały w stratach** — które sygnały były red flagiem (bot ma je ignorować)
- **Wpływ newsów** — korelacja bullish/bearish news z wynikami transakcji
- **Ostatni wzorzec** — ciąg 10 ostatnich decyzji (np. `BUY(72%) → HOLD(45%) → SELL(70%)`)
- **Nota kalibracyjna** — automatyczna instrukcja: jeśli win rate < 35%, bądź bardziej konserwatywny

### Jak bot się poprawia z czasem

Im więcej cykli, tym dokładniejszy profil. Bot widzi:
- Które warunki techniczne + newsowe faktycznie działały dla danego symbolu
- Kiedy był za pewny siebie (high confidence → strata)
- Kiedy news miał realny wpływ vs był szumem

Profil jest czytany i stosowany przy **każdej** decyzji — bot nie czeka na ręczną konfigurację.

---

## Zarządzanie ryzykiem

| Parametr | Domyślnie | Opis |
|----------|-----------|------|
| `max_position_pct` | 10% | Max % konta na jedną pozycję |
| `max_daily_loss_pct` | 3% | Stop dzienny — wstrzymuje handel |
| `stop_loss_pct` | 2% | Stop-loss od ceny wejścia (fallback gdy LLM nie poda) |
| `take_profit_pct` | 3.5% | Take-profit od ceny wejścia (fallback) |
| `max_open_positions` | 20 | Max jednoczesnych pozycji |
| `min_confidence` | 60% | Minimalna pewność AI do wejścia |

**SL/TP są egzekwowane przez silnik** — na początku każdego cyklu bot sprawdza wszystkie otwarte pozycje i zamyka te, które osiągnęły poziom stop-loss lub take-profit.

Parametry ryzyka zmieniasz w zakładce **Ustawienia → Risk**.

### Kiedy bot sprzedaje / zamyka pozycję

| Sytuacja | Akcja |
|----------|-------|
| LLM → SELL + otwarta pozycja long | Zamknięcie longa (market sell) |
| LLM → SELL + brak pozycji | Otwarcie shorta (jeśli risk OK) |
| LLM → BUY + otwarta pozycja short | Zamknięcie shorta (cover) |
| Cena ≤ stop_loss (long) | Automatyczne zamknięcie SL_EXIT |
| Cena ≥ take_profit (long) | Automatyczne zamknięcie TP_EXIT |
| Dzienny stop aktywny | Wstrzymanie wszelkich nowych zleceń |

---

## Short selling

Bot obsługuje pozycje krótkie (short selling):

- **Sygnał SELL bez pozycji** → bot otwiera short (zlecenie `sell`)
- **Sygnał BUY z otwartym shortem** → bot zamyka short (COVER, zlecenie `buy`)
- SL/TP dla shortów są odwrócone: SL powyżej ceny wejścia, TP poniżej

> **Paper trading:** Alpaca pozwala shortować wszystkie symbole bez ograniczeń.  
> **Live trading:** wymagane konto margin; nie wszystkie symbole są `shortable`.

Bot **nie handluje** walutami, kontraktami futures ani opcjami — wyłącznie akcje i ETF-y rynku US.

---

## Bezpieczeństwo kluczy API

1. **Nigdy** nie commituj pliku `.env` do Git — jest w `.gitignore`
2. Używaj **paper trading** podczas testów i nauki
3. Zacznij od małych kwot przy live tradingu
4. Ustaw limity w panelu Alpaca (max dzienna strata, max zlecenie)
5. Regularnie rotuj klucze API (np. co miesiąc)
6. Po zrotowaniu kluczy: wpisz nowe w **Ustawienia → API** i kliknij **Zapisz klucze**

---

## Monitorowanie i logi

Logi dostępne bezpośrednio w zakładce **Logi** — podgląd na żywo bez otwierania plików.

| Plik | Zawartość |
|------|-----------|
| `logs/last_logs.log` | Główny log systemu (nadpisywany przy każdym starcie) |
| `data/trades.csv` | Historia transakcji (CSV, dołączany) |
| `data/ai_decisions.jsonl` | Decyzje AI w formacie JSON Lines (dołączany) |
| `data/news.jsonl` | Newsy z Finnhub z treścią artykułów (dołączany) |
| `data/symbol_brain.json` | Scoring ~12 000 symboli (nadpisywany, format kompaktowy) |
| `data/brain_journal.json` | Rekomendacje i pamięć BrainBota (nadpisywany) |

### Format trades.csv

```csv
timestamp,symbol,action,qty,price,order_id,stop_loss,take_profit,confidence,ai_reasoning_summary
2024-01-15T10:30:15,AAPL,BUY,54,185.20,abc123,181.50,192.61,0.72,RSI w strefie neutralnej...
```

### Typy akcji w trades.csv

| Akcja | Znaczenie |
|-------|-----------|
| `BUY` | Otwarcie pozycji długiej |
| `SELL` | Zamknięcie pozycji długiej |
| `SHORT` | Otwarcie pozycji krótkiej |
| `COVER` | Zamknięcie pozycji krótkiej |
| `SL_EXIT` | Automatyczne zamknięcie przez stop-loss |
| `TP_EXIT` | Automatyczne zamknięcie przez take-profit |

---

## Rozwiązywanie problemów

### "Ollama niedostępna"

Upewnij się, że Ollama jest uruchomiona przed startem aplikacji. Sprawdź w przeglądarce: `http://localhost:11434`. Jeśli strona nie odpowiada — uruchom Ollama z menu Start.

Aby pobrać model (jeśli jeszcze nie masz):
```bash
ollama pull mistral
```

### "Unauthorized" przy Alpaca API

- Upewnij się że używasz kluczy z właściwego panelu — klucze **Paper** i **Live** są oddzielne
- W zakładce Ustawienia → Broker sprawdź czy tryb (Paper/Live) zgadza się z typem kluczy
- Kliknij **Sprawdź API** — zobaczysz dokładny komunikat błędu

### "Brak kluczy Alpaca"

- Klucze wpisz w **Ustawienia → API** i kliknij **Zapisz klucze**
- Aplikacja potrzebuje restartu jeśli klucze były wpisane ręcznie do `.env` bez użycia GUI

### LLM odpowiada wolno

- Zmień model na lżejszy: **Ustawienia → AI** → `phi3:mini`
- Zwiększ timeout: **Ustawienia → AI** → pole Timeout

### Transakcje nie są wykonywane mimo sygnałów BUY

- Sprawdź `min_confidence` w **Ustawienia → Risk** (domyślnie 60%)
- Sprawdź czy rynek jest otwarty (Alpaca handluje tylko NYSE hours: 9:30–16:00 ET)
- Sprawdź zakładkę **Dashboard** — czy nie aktywował się dzienny stop-loss
- Sprawdź zakładkę **BrainBot** — TradingBot handluje tylko symbolami z dziennika rekomendacji; jeśli dziennik jest pusty, bot czeka na rekomendacje BrainBota

### BrainBot nie pokazuje rekomendacji po starcie

- Jeśli to pierwsze uruchomienie: poczekaj na zakończenie skanowania inicjalizacyjnego (zakładka BrainBot → status)
- Jeśli masz już dane: BrainBot aktualizuje rekomendacje co godzinę po hourly refresh — sprawdź log w zakładce BrainBot

### Newsy nie pojawiają się w zakładce News

- Sprawdź klucz Finnhub w **Ustawienia → API** — kliknij **Sprawdź**
- Zaczekaj minutę — NewsPoller pobiera automatycznie, status widoczny w prawym górnym rogu zakładki
- Upewnij się że zakres dat jest ustawiony na bieżący tydzień

### NewsPoller pobiera newsy, ale bez treści artykułów

- Upewnij się że `trafilatura` jest zainstalowana: `pip install trafilatura`
- Niektóre serwisy blokują scraperów — treść będzie pusta, ale nagłówek i summary nadal trafiają do AI

---

## Disclaimer

**Ten program służy wyłącznie do celów edukacyjnych.**

- Trading automatyczny niesie ryzyko utraty kapitału
- Przeszłe wyniki nie gwarantują przyszłych zysków
- Zawsze testuj na paper tradingu przed użyciem prawdziwych pieniędzy
- Autor nie ponosi odpowiedzialności za straty finansowe
