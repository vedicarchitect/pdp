# PDP App (Flutter)

Native trading client for the PDP backend — dark, minimalist, tuned for live
market data. Targets **Android** and **Windows desktop** from one Dart codebase.

Stack: Flutter · Riverpod · go_router · web_socket_channel · dio · fl_chart ·
google_fonts (Inter).

## First-time setup

Requires the [Flutter SDK](https://docs.flutter.dev/get-started/install) on PATH
(`flutter --version`). The repo tracks `lib/`, `pubspec.yaml`, and tests; the
platform host folders are generated locally:

```bash
cd app
flutter create . --platforms=android,windows   # one-time: creates android/ + windows/
flutter pub get
```

## Run

```bash
# Offline demo — simulated live feed, no backend needed
flutter run -d windows --dart-define=USE_MOCK=true

# Live against the local API (start it first: `task dev` in the repo root)
flutter run -d windows \
  --dart-define=API_BASE=http://localhost:8000 \
  --dart-define=WS_BASE=ws://localhost:8000

# Android device on the same LAN — point at the host machine's IP
flutter run -d <device-id> \
  --dart-define=API_BASE=http://<host-ip>:8000 \
  --dart-define=WS_BASE=ws://<host-ip>:8000
```

`flutter devices` lists targets. Defaults (no defines): `http://localhost:8000`
/ `ws://localhost:8000`, mock off.

| Define     | Default                  | Purpose                          |
|------------|--------------------------|----------------------------------|
| `API_BASE` | `http://localhost:8000`  | REST base (`/api/v1/...`)        |
| `WS_BASE`  | `ws://localhost:8000`    | WebSocket base (`/ws/...`)       |
| `USE_MOCK` | `false`                  | Simulated live data, zero backend|

## Test & lint

```bash
flutter analyze
flutter test
```

## Build

```bash
flutter build windows   # → build/windows/x64/runner/Release/
flutter build apk       # → build/app/outputs/flutter-apk/
```

## Layout

```
lib/
  main.dart                       ProviderScope → MaterialApp.router (dark theme)
  core/
    theme/        app_colors.dart · app_theme.dart (Inter, dark tokens)
    config/       app_config.dart (API_BASE / WS_BASE / USE_MOCK)
    network/      api_client.dart (dio) · ws_client.dart (backoff reconnect) · connection_status.dart
    router/       app_router.dart (go_router ShellRoute)
  shared/
    format.dart                   Indian-rupee formatting
    widgets/      pnl_text.dart · stat_card.dart · mode_badge.dart · connection_badge.dart
  features/
    shell/        app_shell.dart (NavigationBar ↔ NavigationRail) · placeholder_screen.dart
    portfolio/
      domain/        position.dart · portfolio_summary.dart · portfolio_snapshot.dart
      data/          portfolio_source.dart · live_portfolio_source.dart · mock_portfolio_source.dart
      application/   portfolio_providers.dart (source select · stream · mode · pnl history)
      presentation/  portfolio_screen.dart · pnl_chart.dart (fl_chart)
```

New screens follow the portfolio pattern: a `Source` interface (live + mock)
behind a Riverpod `StreamProvider`, consumed by a `ConsumerWidget`.
