import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'core/observability/log_shipper.dart';
import 'core/router/app_router.dart';
import 'core/theme/app_theme.dart';

void main() {
  FlutterError.onError = (details) {
    FlutterError.presentError(details);
    LogShipper.instance.ship(
      level: 'error',
      event: details.exceptionAsString(),
      screen: 'flutter_error',
      context: {'library': details.library ?? ''},
    );
  };
  runApp(const ProviderScope(child: TradingApp()));
}

class TradingApp extends StatelessWidget {
  const TradingApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp.router(
      title: 'PDP',
      debugShowCheckedModeBanner: false,
      theme: buildAppTheme(),
      routerConfig: appRouter,
    );
  }
}
