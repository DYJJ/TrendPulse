// TrendPulse 应用基础冒烟测试
//
// 验证应用能正常启动并显示主页面

import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:provider/provider.dart';
import 'package:trendpulse/api/api_client.dart';
import 'package:trendpulse/main.dart';
import 'package:trendpulse/providers/analysis_provider.dart';
import 'package:trendpulse/providers/posts_provider.dart';
import 'package:trendpulse/providers/subscription_provider.dart';

void main() {
  testWidgets('应用启动冒烟测试', (WidgetTester tester) async {
    final apiClient = ApiClient();
    await tester.pumpWidget(TrendPulseApp(apiClient: apiClient));

    // 验证底部导航栏存在且包含四个导航目标
    expect(find.byType(NavigationBar), findsOneWidget);
    expect(find.byType(NavigationDestination), findsNWidgets(4));
  });
}
