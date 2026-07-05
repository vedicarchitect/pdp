import 'package:shared_preferences/shared_preferences.dart';

/// Persists the user's personal watchlist locally (no backend watchlist
/// capability exists in this change). Symbols are free-text (e.g. index or
/// instrument names); resolving live quotes for them is the caller's job.
abstract interface class WatchlistRepository {
  Future<List<String>> load();
  Future<void> save(List<String> symbols);
}

class SharedPrefsWatchlistRepository implements WatchlistRepository {
  static const _key = 'dashboard_watchlist_symbols';

  @override
  Future<List<String>> load() async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getStringList(_key) ?? const [];
  }

  @override
  Future<void> save(List<String> symbols) async {
    final prefs = await SharedPreferences.getInstance();
    await prefs.setStringList(_key, symbols);
  }
}

class InMemoryWatchlistRepository implements WatchlistRepository {
  List<String> _symbols = const ['NIFTY', 'BANKNIFTY'];

  @override
  Future<List<String>> load() async => _symbols;

  @override
  Future<void> save(List<String> symbols) async {
    _symbols = symbols;
  }
}
