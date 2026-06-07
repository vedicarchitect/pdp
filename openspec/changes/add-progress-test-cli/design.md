## Context

The PDP project has implemented Dhan broker integration, portfolio P&L tracking, and options analytics (Greeks calculation). We need a CLI tool to validate these components work together correctly during development and manual testing. Currently there's no easy way to debug broker connectivity or verify position state without standing up the full web server.

## Goals / Non-Goals

**Goals:**
- Provide a quick CLI entrypoint to test Dhan broker connectivity
- Display current positions from the Dhan account
- Display portfolio summary (holdings, MTM P&L, etc.)
- Fetch and display current week option chain with computed Greeks
- Calculate and display Greeks for all open positions
- Enable developers to debug integration without UI

**Non-Goals:**
- Real-time monitoring or alerting (one-shot commands only)
- GUI or interactive shell
- Persistence of results
- Broadcasting results to WebSocket (that's the server's job)

## Decisions

**1. Architecture: Reuse existing engines and SDK**
   - Use the Dhan SDK directly (no new abstraction layer)
   - Leverage existing portfolio engine for position state
   - Use existing options analytics module for Greek calculations
   - Rationale: Validates that engines work independently of the web server; minimal new code

**2. CLI Framework: Use Click for simple commands**
   - Organize as separate subcommands (positions, portfolio, option-chain, greeks)
   - Rationale: Click is lightweight, integrates well with Python async, easy to extend

**3. Output Format: Structured table output via Rich or simple JSON**
   - Use Rich tables for human readability during development
   - Support JSON output flag for automation
   - Rationale: Balances readability with scriptability

**4. Environment Defaults: Paper engine unless LIVE=1 + configured broker**
   - Respects CLAUDE.md non-negotiable: "Paper engine unless LIVE=1"
   - Rationale: Safe by default; prevents accidental live trading during testing

**5. Data sources for Greeks calculation**
   - Fetch option chain from Dhan for current week
   - Use live bid/ask for ATM options as spot price proxy if available
   - Fall back to last traded price if live market data unavailable
   - Rationale: Aligns with existing options analytics patterns

## System Architecture Diagram

```mermaid
graph TB
    subgraph "User Interface Layer"
        CLI["🖥️ pdp-cli<br/>(Click CLI)<br/>new component"]
        WEB["🌐 Web Server<br/>(REST/WebSocket)<br/>existing"]
    end
    
    subgraph "Business Logic Layer"
        PORT["📊 Portfolio Engine<br/>MTM P&L, holdings<br/>aggregation"]
        OPT["📈 Options Analytics<br/>Greeks calculation,<br/>IV, chain analysis"]
        TRADE["🔄 Trading Engine<br/>order execution,<br/>position tracking"]
    end
    
    subgraph "Market Data & Broker Integration"
        MKT["🔌 Market Engine<br/>tick ingestion,<br/>live pricing"]
        DHAN["🏦 Dhan SDK<br/>positions, orders,<br/>option chains"]
    end
    
    subgraph "Data Layer"
        subgraph "Paper Engine"
            PAPER["📝 Paper Ledger<br/>simulated trades,<br/>P&L tracking"]
        end
        subgraph "Live Account"
            LIVE["💰 Live Ledger<br/>Dhan account<br/>state"]
        end
        LEDGER["🗄️ PostgreSQL<br/>trade history,<br/>audit log"]
    end
    
    CLI -->|queries| PORT
    CLI -->|queries| OPT
    CLI -->|queries| DHAN
    WEB -->|queries| PORT
    WEB -->|queries| OPT
    WEB -->|queries| TRADE
    
    PORT -->|reads positions| PAPER
    PORT -->|reads positions| LIVE
    PORT -->|reads ticks| MKT
    
    OPT -->|reads IV, chain| DHAN
    OPT -->|reads spot| MKT
    
    TRADE -->|executes| DHAN
    TRADE -->|writes| PAPER
    TRADE -->|writes| LEDGER
    
    MKT -->|reads| DHAN
    DHAN -->|live data| LIVE
    DHAN -->|historical| LEDGER
    
    ENV["⚙️ LIVE=0/1<br/>BROKER_CONFIG"] -.->|selects| PAPER
    ENV -.->|selects| LIVE
```

**System composition:**
- CLI layer is thin: delegates all logic to existing engines
- CLI can query Portfolio Engine directly (bypasses Trading Engine)
- Market Engine feeds live tick data to analytics
- Paper vs. live selected by LIVE environment variable
- All data ultimately persists to PostgreSQL ledger

## Data Flow Diagram

```mermaid
graph LR
    A["pdp-cli<br/>(Click CLI)"] --> B["positions<br/>command"]
    A --> C["portfolio<br/>command"]
    A --> D["option-chain<br/>command"]
    A --> E["greeks<br/>command"]
    
    B --> B1["Dhan SDK<br/>fetch_positions"]
    B --> B2["Output: positions<br/>symbol, qty, price, P&L"]
    
    C --> C1["Portfolio Engine<br/>get_aggregated_metrics"]
    C --> C2["Output: portfolio<br/>invested, market_val,<br/>realized P&L, MTM P&L"]
    
    D --> D1["Dhan SDK<br/>fetch_option_chain<br/>current week expiry"]
    D --> D2["Output: option chain<br/>strike, bid, ask,<br/>OI, IV"]
    
    E --> E1["Portfolio Engine<br/>get_positions"]
    E --> E2["Dhan SDK<br/>fetch_option_chain<br/>+ spot price"]
    E --> E3["Options Analytics<br/>calculate_greeks"]
    E --> E4["Output: greeks<br/>delta, gamma,<br/>theta, vega, rho"]
    
    B2 --> F["Formatter<br/>Rich tables | JSON"]
    C2 --> F
    D2 --> F
    E4 --> F
    
    F --> G["User Output<br/>stdout/file"]
    
    H["Environment<br/>LIVE=0/1<br/>BROKER_CONFIG"] -.-> A
```

**Command-level data flow:**
- All commands are stateless one-shot queries
- Commands fetch from live Dhan account (LIVE=1) or paper engine (default LIVE=0)
- Greeks command is the most complex: aggregates positions + fetches option chain + calculates
- All output goes through unified formatter (Rich tables or JSON)

## Risks / Trade-offs

- [Risk] Dhan API rate limits if CLI is called too frequently
  - Mitigation: Document expected usage (one-shot validation); can add caching layer if needed

- [Risk] Greeks calculation requires IV data which may not be available for illiquid options
  - Mitigation: Display warning/null if Greeks cannot be computed; focus on liquid weeklies

- [Risk] Paper engine vs. live account state may diverge
  - Mitigation: Expected behavior; document that CLI validates integration not trading correctness

- [Risk] CLI is a new entrypoint that duplicates some portfolio engine logic
  - Mitigation: Keep CLI thin; delegate all business logic to existing engines

## Open Questions

- Should CLI support filtering (e.g., only show options expiring Friday)? → Defer to v2
- Should we persist CLI output to logs for debugging? → Defer; use stdout/logs only
