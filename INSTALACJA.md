# 777moneymaker — Instalacja

## Spis treści
1. [Wymagania wstępne](#wymagania-wstępne)
2. [Krok 1: Pobierz projekt](#krok-1-pobierz-projekt)
3. [Krok 2: Środowisko Python](#krok-2-środowisko-python)
4. [Krok 3: Zainstaluj Ollama i model AI](#krok-3-zainstaluj-ollama-i-model-ai)
5. [Krok 4: Utwórz plik .env](#krok-4-utwórz-plik-env)
6. [Krok 5: Uruchom aplikację](#krok-5-uruchom-aplikację)

---

## Wymagania wstępne

- **Python 3.10+**
- **8 GB RAM** (dla modeli Mistral/Llama; 4 GB wystarczy dla phi3:mini)
- Połączenie z internetem (dane rynkowe z Alpaca IEX feed, API Finnhub)
- Konto na [alpaca.markets](https://alpaca.markets) (darmowe, paper trading wystarczy na start)

Sprawdź wersję Pythona:
```bash
python --version
```

---

## Krok 1: Pobierz projekt

```bash
cd C:\Users\kubam\Documents\Projekty\777moneymaker
```

---

## Krok 2: Środowisko Python

### Windows

```powershell
# Utwórz środowisko wirtualne
python -m venv venv

# Aktywuj
venv\Scripts\activate

# Zainstaluj zależności
pip install -r requirements.txt
```

### Linux / macOS

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

> Środowisko wirtualne musisz aktywować za każdym razem gdy otwierasz nowy terminal. Po aktywacji zobaczysz `(venv)` na początku linii.

---

## Krok 3: Zainstaluj Ollama i model AI

1. Pobierz i zainstaluj Ollama: **https://ollama.ai/download**

2. Po instalacji pobierz model AI (wybierz jeden):

```bash
# Mistral 7B — rekomendowany (dobra jakość, ~4GB RAM)
ollama pull mistral

# Phi-3 Mini — lżejszy (~2GB RAM), szybszy
ollama pull phi3:mini

# Llama 3 8B — alternatywa dla Mistrala
ollama pull llama3
```

3. Uruchom serwer Ollama (Linux/macOS):

```bash
ollama serve
```

> Na Windows Ollama uruchamia się automatycznie w tle po instalacji.

4. Sprawdź czy działa:

**Windows:**
```powershell
curl.exe http://localhost:11434/api/tags
```

**Linux / macOS:**
```bash
curl http://localhost:11434/api/tags
```

Powinieneś zobaczyć JSON z listą zainstalowanych modeli.

---

## Krok 4: Utwórz plik .env

### Windows

```powershell
copy .env.example .env
```

### Linux / macOS

```bash
cp .env.example .env
```

Plik `.env` musi zawierać klucze Alpaca:

```env
ALPACA_API_KEY=twój_klucz_alpaca
ALPACA_SECRET_KEY=twój_secret_alpaca

# Opcjonalnie — newsy dla AI (darmowe konto na finnhub.io)
FINNHUB_API_KEY=twój_klucz_finnhub
```

> Klucze możesz też wpisać bezpośrednio w aplikacji przez **Ustawienia → API** — zostaną zapisane do `.env` automatycznie.

**Gdzie znaleźć klucze Alpaca:**
- Zaloguj się na [alpaca.markets](https://alpaca.markets)
- Paper trading: "Paper Accounts" → "View" → "API Keys" → "Regenerate"
- Live trading: "Live" → "API Keys"

---

## Krok 5: Uruchom aplikację

```bash
# Upewnij się że venv jest aktywny
venv\Scripts\activate     # Windows
source venv/bin/activate  # Linux/macOS

python dashboard.py
```

Przy pierwszym uruchomieniu:
1. Przejdź do **Ustawienia → Broker** — wybierz tryb **Paper** (bezpieczny start)
2. Przejdź do **Ustawienia → API** — wpisz klucze Alpaca, kliknij **Zapisz klucze**
3. Kliknij **Sprawdź API** — upewnij się że połączenie działa
4. Wróć na **Dashboard** — dane konta pojawiają się automatycznie
5. Kliknij **▶ Start** aby uruchomić bota

> **Pierwsze uruchomienie BrainBota:** przy całkowicie pustej bazie danych BrainBot wykona jednorazowy inicjalizacyjny skan rynku (~12 000 symboli). Trwa to kilkanaście minut — status widoczny w zakładce **BrainBot**. Przy kolejnych startach bot wczytuje dane z poprzedniej sesji i startuje natychmiast.

---

## Struktura katalogów po instalacji

```
data/                        ← tworzone automatycznie przy pierwszym uruchomieniu
├── trades.csv               ← historia transakcji
├── ai_decisions.jsonl       ← decyzje AI
├── news.jsonl               ← newsy z Finnhub
├── symbol_brain.json        ← scoring symboli (~12 000 wpisów, kompaktowy JSON)
└── brain_journal.json       ← rekomendacje i pamięć BrainBota

logs/                        ← tworzone automatycznie
└── last_logs.log            ← bieżący log systemu
```

Katalogi `data/` i `logs/` są tworzone automatycznie — nie musisz ich tworzyć ręcznie.

---

## Rozwiązywanie problemów instalacji

**`pip install` kończy się błędem przy PySide6`**
- Upewnij się że masz Python 3.10+ (`python --version`)
- Zaktualizuj pip: `python -m pip install --upgrade pip`

**`ModuleNotFoundError` przy uruchomieniu**
- Sprawdź czy środowisko wirtualne jest aktywne (`(venv)` w terminalu)
- Uruchom ponownie `pip install -r requirements.txt`

**Aplikacja startuje, ale dashboard jest pusty**
- Sprawdź klucze Alpaca w **Ustawienia → API**
- Kliknij przycisk **↻** (odśwież) na Dashboard
- Sprawdź zakładkę Logi — powinny pojawić się komunikaty o połączeniu

Po wykonaniu wszystkich kroków zapoznaj się z `INSTRUKCJA.md` aby dowiedzieć się jak korzystać z aplikacji.
