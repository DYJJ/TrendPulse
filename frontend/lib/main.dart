import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:trendpulse/providers/analysis_provider.dart';
import 'package:trendpulse/providers/posts_provider.dart';
import 'package:trendpulse/providers/subscription_provider.dart';
import 'package:trendpulse/screens/home_screen.dart';
import 'package:trendpulse/api/api_client.dart';

void main() {
  final apiClient = ApiClient();
  runApp(TrendPulseApp(apiClient: apiClient));
}

/// TrendPulse 舆情脉冲应用入口
class TrendPulseApp extends StatelessWidget {
  final ApiClient apiClient;

  const TrendPulseApp({super.key, required this.apiClient});

  @override
  Widget build(BuildContext context) {
    return MultiProvider(
      providers: [
        ChangeNotifierProvider(create: (_) => AnalysisProvider(apiClient)),
        ChangeNotifierProvider(create: (_) => PostsProvider(apiClient)),
        ChangeNotifierProvider(create: (_) => SubscriptionProvider(apiClient)),
      ],
      child: MaterialApp(
        title: 'TrendPulse',
        debugShowCheckedModeBanner: false,
        theme: _buildTheme(),
        home: const HomeScreen(),
      ),
    );
  }

  ThemeData _buildTheme() {
    // 苹果风格：纯黑底、极简、大留白、系统字体
    const bg = Color(0xFF000000);
    const surface = Color(0xFF1C1C1E);
    const card = Color(0xFF1C1C1E);
    const accent = Color(0xFF0A84FF); // iOS蓝
    const textPrimary = Color(0xFFFFFFFF);
    const textSecondary = Color(0xFF8E8E93);
    const separator = Color(0xFF38383A);

    return ThemeData(
      useMaterial3: true,
      brightness: Brightness.dark,
      scaffoldBackgroundColor: bg,
      colorScheme: const ColorScheme.dark(
        primary: accent,
        secondary: accent,
        surface: surface,
        onSurface: textPrimary,
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: Colors.transparent,
        elevation: 0,
        centerTitle: false,
      ),
      cardTheme: CardThemeData(
        color: card,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(13)),
      ),
      dividerColor: separator,
      textTheme: const TextTheme(
        displayLarge: TextStyle(fontSize: 34, fontWeight: FontWeight.w700, letterSpacing: 0.37, color: textPrimary),
        headlineLarge: TextStyle(fontSize: 28, fontWeight: FontWeight.w700, letterSpacing: 0.36, color: textPrimary),
        headlineMedium: TextStyle(fontSize: 22, fontWeight: FontWeight.w700, letterSpacing: 0.35, color: textPrimary),
        titleLarge: TextStyle(fontSize: 20, fontWeight: FontWeight.w600, letterSpacing: 0.38, color: textPrimary),
        titleMedium: TextStyle(fontSize: 17, fontWeight: FontWeight.w600, letterSpacing: -0.41, color: textPrimary),
        bodyLarge: TextStyle(fontSize: 17, fontWeight: FontWeight.w400, letterSpacing: -0.41, color: textPrimary),
        bodyMedium: TextStyle(fontSize: 15, fontWeight: FontWeight.w400, letterSpacing: -0.24, color: textPrimary),
        bodySmall: TextStyle(fontSize: 13, fontWeight: FontWeight.w400, letterSpacing: -0.08, color: textSecondary),
        labelLarge: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, letterSpacing: -0.24, color: accent),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: const Color(0xFF2C2C2E),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: BorderSide.none,
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: BorderSide.none,
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(10),
          borderSide: const BorderSide(color: accent, width: 1),
        ),
        contentPadding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
        hintStyle: const TextStyle(color: textSecondary, fontSize: 17, letterSpacing: -0.41),
      ),
      navigationBarTheme: NavigationBarThemeData(
        height: 50,
        backgroundColor: const Color(0xFF1C1C1E).withValues(alpha: 0.94),
        surfaceTintColor: Colors.transparent,
        indicatorColor: Colors.transparent,
        labelBehavior: NavigationDestinationLabelBehavior.alwaysShow,
        iconTheme: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) {
            return const IconThemeData(size: 24, color: accent);
          }
          return const IconThemeData(size: 24, color: textSecondary);
        }),
        labelTextStyle: WidgetStateProperty.resolveWith((states) {
          if (states.contains(WidgetState.selected)) {
            return const TextStyle(fontSize: 10, fontWeight: FontWeight.w500, color: accent);
          }
          return const TextStyle(fontSize: 10, fontWeight: FontWeight.w500, color: textSecondary);
        }),
      ),
    );
  }
}
