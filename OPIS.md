# 777moneymaker — Instrukcja i opis działania aplikacji

## Uruchamianie

```
python dashboard.py          # GUI (zalecane)
python main.py               # tryb konsolowy bez GUI
python main.py --paper       # wymuszony tryb paper
python main.py --once        # jeden cykl i wyjście
python main.py --check       # sprawdź połączenia i wyjdź
```

---

## Jak działa system — dwubotowy model równoległy

Program składa się z dwóch niezależnych agentów AI działających jednocześnie w osobnych wątkach:

| Agent | Rola |
|-------|------|
| **BrainBot** | Skanuje cały rynek (~12 000 symboli), ocenia je punktowo i buduje listę rekomendacji |
| **TradeBot** | Handluje wyłącznie na symbolach z listy rekomendacji BrainBota — nigdy sam nie szuka okazji |

Oba agenty startują ręcznie z zakładki **Dashboard**. Dane konta Alpaca i newsy odświeżają się automatycznie niezależnie od stanu botów.

---

## Zakładki aplikacji

### 1. Dashboard (📊)

Główny ekran startowy z przeglądem stanu systemu.

**Karty statystyk (górny rząd):**
- **Available Cash** — gotówka dostępna na koncie Alpaca
- **Portfolio Value** — łączna wartość otwartych pozycji
- **Open Positions** — liczba aktualnie otwartych pozycji
- **Daily P&L** — zysk/strata od początku sesji (liczy się od startu aplikacji)

**Panel TradeBot:**
- Status: Działa / Zatrzymany / Błąd
- Tryb: PAPER lub LIVE
- Przyciski **▶ Start** i **■ Stop** — uruchamiają i zatrzymują TradeBota
- Przycisk **↻** — ręczne odświeżenie danych konta z Alpaca

**Panel BrainBot:**
- Status: Działa / Zatrzymany
- Krótki opis aktualnej czynności (np. "LLM skan top-50…")
- Przyciski **▶ Start** i **■ Stop** — uruchamiają i zatrzymują BrainBota

**Wykres equity (session):**
- Linia P&L od początku sesji względem kapitału startowego
- Zielona gdy na plusie, czerwona gdy na minusie
- Wartość aktualna + zmiana w $ i %

**Tabela Recent Trades:**
- Ostatnie 20 transakcji z pliku `data/trades.csv`
- Kolumny: Czas, Symbol, Akcja, Ilość, Cena, SL, TP, Pewność AI
- BUY/COVER/TP_EXIT = zielone, SELL/SHORT/SL_EXIT = czerwone

**Ostatni sygnał AI:**
- Jeden wiersz z ostatnią decyzją LLM lub wykonaną transakcją

> Dane Alpaca odświeżają się automatycznie co 30 sekund niezależnie od stanu botów.

---

### 2. Market (📈)

Tabela przeglądu rynku dla obserwowanych symboli.

**Toolbar:**
- Pole **Symbol** + przycisk wyszukiwania — wpisz ticker (np. `AAPL`) i Enter, żeby dodać dowolny symbol do tabeli
- Przycisk **⟳ Odśwież** — ponownie pobiera dane rynkowe dla wszystkich widocznych symboli

**Tabela kolumny:**
| Kolumna | Opis |
|---------|------|
| Symbol | Ticker |
| Cena | Aktualna cena zamknięcia |
| Zmiana % | Zmiana względem poprzedniego zamknięcia (kolor) |
| Wolumen | Dzienny wolumen obrotu |
| RSI(14) | Wskaźnik RSI z timeframe'u dziennego |
| Sygnał | Interpretacja RSI: BUY / SELL / Bullish / Bearish / Neutral |
| Trend tygodniowy | Trend z timeframe'u tygodniowego (STRONG UPTREND itp.) |
| Pozycja | ▲ LONG / ▼ SHORT + niezrealizowany P&L, jeśli pozycja otwarta |

**Dwuklik na wierszu** — otwiera wykres dla wybranego symbolu w zakładce Chart.

Tabela automatycznie wypełnia się symbolami z otwartych pozycji i z listy obserwowanych w zakładce Chart. Po każdym cyklu TradeBota dane są odświeżane.

---

### 3. Chart (🕯)

Interaktywny wykres świecowy z wskaźnikami technicznymi.

**Toolbar:**
- Przyciski **1 / 4 / 6 / 8** — układ siatki: 1 wykres pełnoekranowy lub 4/6/8 miniaturek jednocześnie
- Przycisk **↻ Refresh** — ponownie pobiera dane dla wszystkich aktywnych wykresów
- Przycisk **＋ Symbole** — otwiera panel zarządzania obserwowanymi symbolami

**Panel zarządzania symbolami (＋ Symbole):**
- Sekcja **Otwarte pozycje** — symbole z aktywnymi transakcjami (nie można usunąć)
- Sekcja **Obserwowane** — ręcznie dodane symbole (ikona × usuwa)
- Pole tekstowe — wpisz ticker i Enter lub ＋ aby dodać nowy symbol

**Wykres (tryb pełnoekranowy — layout 1):**
- **Świece** — zielone (wzrostowe) / czerwone (spadkowe)
- **EMA20** — niebieska linia
- **EMA50** — żółta linia
- **Trójkąt wejścia** — zielony znacznik w miejscu otwarcia pozycji
- **Linia SL** — czerwona przerywana pozioma linia stop-loss
- **Linia TP** — zielona przerywana pozioma linia take-profit
- **Crosshair** — krzyżyk śledzący kursor z dokładnym tooltipem (data, OHLC, wolumen, RSI)
- **Subplot wolumenu** — słupki wolumenu (zielone/czerwone), połączone z osią X wykresu głównego
- **Subplot RSI** — linia RSI z poziomami 30 i 70

W trybie **4/6/8 wykresów** podploty są ukryte, świece kompaktowe — widać więcej symboli naraz.

Kliknięcie nazwy symbolu w nagłówku wykresu (layout 1) otwiera menu do przełączenia między obserwowanymi symbolami.

---

### 4. BrainBot (🧠)

Centrum sterowania i monitorowania BrainBota — autonomicznego skanera rynku. Zawiera 4 podzakładki.

#### 4.1 Konsola

Strumień logów BrainBota w czasie rzeczywistym — każda decyzja skanera i zmiana statusu pojawia się tutaj na bieżąco.

- Wpisy **BUY** kolorowane na zielono, **SELL** na czerwono, **HOLD** szaro
- Wpisy statusowe (np. "Odświeżono score: 600 symboli…") w kolorze złotym
- Licznik wpisów, przycisk **Clear**
- Bufor do 5000 linii — starsze automatycznie usuwane

#### 4.2 Logi

Tabela punktacji symboli z bazy SymbolBrain — stan aktualny wszystkich śledzonych symboli.

- Sortowanie po score, aktywności, sygnale skanera
- Widać: symbol, score (0–1), ostatni sygnał LLM, pewność, timestamp
- Status skanera nad tabelą: ile przeskanowanych, postęp %

#### 4.3 Dziennik

Wynik pracy BrainBota — lista symboli rekomendowanych do handlu dla TradeBota.

**Pasek statystyk:**
- Przeskanowane — łączna liczba symboli z ostatniego cyklu
- Rekomendowane — ile symboli w aktywnej liście rekomendacji
- W obserwacji — ile symboli na liście "watch later"
- Ostatni skan — czas od poprzedniego cyklu BrainBota

**Tabela "POLECANE TERAZ" (lewa strona):**
- Symbole które TradeBot może handlować
- Kolumny: Symbol, Akcja (BUY/SELL), Pewność, Score
- Aktualizowana automatycznie co 15 sekund

**Tabela "OBSERWUJ PÓŹNIEJ" (prawa strona górna):**
- Symbole z niskim ale rosnącym score — kandydaci na następny cykl
- Kolumny: Symbol, Score

**"NOTATKI UCZENIA" (prawa strona dolna):**
- Automatyczne notatki generowane gdy sygnał BrainBota się odwrócił
- Format: `[czas] SYMBOL: opis co przewidziano i co się stało`
- Do 20 ostatnich notatek

**"WYTYCZNE":**
- Wskazówki strategiczne wyekstrahowane z czatu z użytkownikiem
- Np. "Skup się na spółkach technologicznych", "Unikaj małych spółek"

#### 4.4 Czat

Interaktywny czat z BrainBotem — możliwość zadawania pytań i wydawania poleceń strategicznych.

- Wpisz wiadomość i Enter lub przycisk **Wyślij**
- BrainBot odpowiada przez lokalny LLM (Ollama, temperatura 0.7)
- Historia ostatnich 50 wiadomości ładowana automatycznie z journala
- Słowa kluczowe strategiczne ("skup", "unikaj", "focus", "ignore" itp.) są automatycznie zapisywane jako wytyczne i używane w przyszłych skanach

**Przykłady pytań do BrainBota:**
- *"Jakie masz teraz rekomendacje?"*
- *"Skup się na spółkach z sektora energetycznego"*
- *"Unikaj małych spółek poniżej $10"*
- *"Co się stało z TSLA w ostatnim skanie?"*

> Czat działa tylko gdy BrainBot jest uruchomiony. Odpowiedzi mogą zająć kilka sekund.

---

### 5. TradeBot (🤖)

Panel monitorowania TradeBota — aktywnego silnika handlowego. Zawiera 3 podzakładki.

#### 5.1 Console

Logi TradeBota w czasie rzeczywistym — każdy cykl, każda analiza symbolu, każda transakcja.

- Kolorowanie: BUY/COVER/TP_EXIT = zielone, SELL/SHORT/SL_EXIT = czerwone, WARNING = żółte, ERROR = czerwone
- Filtr poziomu: ALL / INFO / WARNING / ERROR
- Auto-scroll: automatycznie przewija na dół przy nowych wpisach; przewiń w górę ręcznie aby wstrzymać
- Wskaźnik "⬇ auto" / "⏸ pauza" pokazuje stan auto-scrollu
- Bufor do 5000 linii

#### 5.2 Positions

Tabela wszystkich aktualnie otwartych pozycji na koncie Alpaca.

**Kolumny:**
| Kolumna | Opis |
|---------|------|
| Symbol | Ticker |
| Side | LONG (zielony) / SHORT (czerwony) |
| Qty | Liczba akcji |
| Entry Price | Średnia cena wejścia |
| Current Price | Aktualna cena rynkowa |
| P&L ($) | Niezrealizowany zysk/strata w dolarach |
| P&L (%) | Niezrealizowany zysk/strata w procentach |
| Stop Loss | Poziom SL ustawiony przy wejściu |
| Take Profit | Poziom TP ustawiony przy wejściu |
| Opened At | Data i godzina otwarcia pozycji |

**Przyciski:**
- **↻ Refresh** — ręczne odświeżenie listy pozycji z Alpaca
- **Close Selected** — natychmiastowe zamknięcie zaznaczonych pozycji zleceniem market (wymaga działającego TradeBota)

#### 5.3 Decisions

Historia wszystkich decyzji AI z pełnym uzasadnieniem.

**Filtry (górna belka):**
- **Od / Do** — zakres dat (kalendarz)
- **Symbol** — lista rozwijana wszystkich symboli w historii
- **Decyzja** — ALL / BUY / SELL / HOLD
- **Szukaj** — wyszukiwanie tekstowe w symbolu i treści rozumowania AI
- **↻ Odśwież** — ponownie wczytuje plik `data/ai_decisions.jsonl`
- Licznik: widoczne / łącznie decyzji

**Tabela (lewa strona):**
- Sortowalna po każdej kolumnie
- Kolumny: Czas, Symbol, Decyzja (kolor), Pewność, Cena, Entry, SL, TP, RSI

**Panel szczegółów (prawa strona):**
Kliknij wiersz, żeby zobaczyć pełne informacje:
- Nagłówek z symbolem, decyzją i pewnością
- Poziomy Entry / Stop Loss / Take Profit
- Snapshot rynkowy: cena, zmiana %, RSI, volume ratio, MACD
- **Rozumowanie AI** — pełny tekst dlaczego LLM podjął daną decyzję
- **Sygnały kluczowe** — lista sygnałów które wpłynęły na decyzję

---

### 6. News (📰)

Przeglądarka newsów rynkowych pobieranych automatycznie przez Finnhub.

**Filtry:**
- **Symbol** — lista rozwijana ze wszystkimi symbolami w bazie newsów; "Wszystkie" pokazuje wszystkie newsy
- **Od / Do** — zakres dat (domyślnie ostatnie 7 dni)

**Tabela:**
| Kolumna | Opis |
|---------|------|
| Data | Data i godzina publikacji artykułu |
| Symbol | Ticker spółki (zielony) lub MARKET (makro/ogólny) |
| Nagłówek | Tytuł artykułu |
| Źródło | Nazwa wydawcy |

**Dwuklik na wierszu** — otwiera artykuł w domyślnej przeglądarce.

Newsy są pobierane automatycznie co 60 sekund przez NewsPoller (w tle, niezależnie od stanu botów). Licznik w prawym dolnym rogu pokazuje datę ostatniego odświeżenia.

> Zakładka News działa tylko gdy skonfigurowany jest klucz `FINNHUB_API_KEY` w Ustawieniach → API. Bez niego bot działa normalnie, ale newsy nie są pobierane.

---

### 7. Settings (⚙️)

Konfiguracja całego systemu podzielona na 5 podzakładek. Każda ma własny przycisk **💾 Zapisz** — zmiana w jednej nie nadpisuje pozostałych.

#### 7.1 Broker

- **Broker** — wybór brokera (aktualnie tylko Alpaca Markets)
- **Tryb** — `paper` (wirtualne pieniądze) lub `live` (prawdziwe pieniądze)
  - Po zmianie na `live` pojawia się czerwone ostrzeżenie
  - Zmiana wymaga restartu botów żeby weszła w życie

#### 7.2 API

**Alpaca API:**
- **API Key** i **Secret Key** — klucze z panelu alpaca.markets
  - Paper i Live mają osobne klucze
  - Przycisk **💾 Zapisz klucze** — zapisuje do pliku `.env`
  - Przycisk **🔌 Sprawdź połączenie** — testuje połączenie i pokazuje equity konta

**Finnhub API:**
- **API Key** — klucz z finnhub.io (darmowy plan wystarczy)
  - Przycisk **💾 Zapisz klucz** — zapisuje do `.env`
  - Przycisk **🔌 Sprawdź połączenie** — testuje klucz pobierając 3 newsy

#### 7.3 AI

Ustawienia lokalnego modelu LLM (Ollama):

| Pole | Opis | Domyślnie |
|------|------|-----------|
| URL | Adres serwera Ollama | `http://localhost:11434` |
| Model | Nazwa modelu | `mistral` |
| Timeout | Maks. czas oczekiwania na odpowiedź LLM | 120s |
| Temperature | Losowość odpowiedzi (0 = deterministyczny) | 0.0 |
| Min Confidence | Minimalna pewność AI do wykonania transakcji | 0.65 |

Zmiana modelu wymaga żeby model był zainstalowany w Ollama (`ollama pull <model>`).

#### 7.4 Risk

Parametry zarządzania ryzykiem:

| Pole | Opis | Domyślnie |
|------|------|-----------|
| Stop Loss | % straty od ceny wejścia do automatycznego zamknięcia | 2% |
| Take Profit | % zysku od ceny wejścia do automatycznego zamknięcia | 3.5% |
| Max Position % | Maks. % equity na jedną pozycję | 10% |
| Daily Loss Limit | % equity — po przekroczeniu bot wstrzymuje handel do północy | 3% |
| Max Open Positions | Maks. liczba jednocześnie otwartych pozycji | 20 |

#### 7.5 Pozostałe

- **Interwał cyklu** — co ile sekund TradeBot uruchamia analizę (domyślnie 60s)

---

## Pasek statusu (dół ekranu)

Trzy stale widoczne informacje:
- **TradeBot: stopped/running** — stan TradeBota
- **BrainBot: initializing…/running** — stan BrainBota
- **Alpaca: paper/live — $XX,XXX** — stan połączenia i equity konta (po prawej)

---

## Pliki danych

| Plik | Zawartość |
|------|-----------|
| `data/trades.csv` | Historia wykonanych transakcji |
| `data/ai_decisions.jsonl` | Pełne decyzje AI z uzasadnieniami |
| `data/news.jsonl` | Newsy pobrane z Finnhub |
| `data/symbol_brain.json` | Scoring i historia ~500 najlepszych symboli |
| `data/brain_journal.json` | Rekomendacje, notatki uczenia, historia czatu BrainBota |
| `logs/last_logs.log` | Logi systemowe (INFO/WARNING/ERROR) |
| `.env` | Klucze API (Alpaca, Finnhub) |
| `config.yaml` | Konfiguracja systemu |

---

## Typowy scenariusz użycia

1. Uruchom `python dashboard.py`
2. Przejdź do **Settings → API** i zapisz klucze Alpaca (i opcjonalnie Finnhub)
3. Sprawdź połączenie przyciskiem **🔌 Sprawdź połączenie**
4. Wróć do **Dashboard** — kliknij **▶ Start** przy BrainBocie
5. Poczekaj aż BrainBot zakończy pierwszy skan i zapełni Dziennik rekomendacjami
6. Kliknij **▶ Start** przy TradeBocie — zacznie handlować na rekomendacjach BrainBota
7. Monitoruj postęp w zakładkach **TradeBot → Console** i **BrainBot → Dziennik**

> BrainBot i TradeBot mogą działać niezależnie. BrainBot może skanować rynek bez aktywnego TradeBota.
