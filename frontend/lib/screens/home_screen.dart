import 'package:flutter/material.dart';
import 'package:trendpulse/screens/dashboard_page.dart';
import 'package:trendpulse/screens/data_flow_page.dart';
import 'package:trendpulse/screens/mindmap_page.dart';
import 'package:trendpulse/screens/search_page.dart';
import 'package:trendpulse/screens/subscription_page.dart';

/// 主页面 - iOS TabBar 风格底部导航
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  int _currentIndex = 0;
  late final List<Widget> _pages;

  @override
  void initState() {
    super.initState();
    _pages = [
      SearchPage(onTaskCompleted: () => _switchTab(1)),
      const DashboardPage(),
      const DataFlowPage(),
      const MindMapPage(),
      const SubscriptionPage(),
    ];
  }

  /// 切换到指定 tab 页
  void _switchTab(int index) {
    setState(() => _currentIndex = index);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: IndexedStack(index: _currentIndex, children: _pages),
      bottomNavigationBar: Container(
        decoration: BoxDecoration(
          border: Border(
            top: BorderSide(color: const Color(0xFF38383A).withValues(alpha: 0.6), width: 0.33),
          ),
        ),
        child: NavigationBar(
          selectedIndex: _currentIndex,
          onDestinationSelected: (i) => setState(() => _currentIndex = i),
          destinations: const [
            NavigationDestination(icon: Icon(Icons.search), label: '搜索'),
            NavigationDestination(icon: Icon(Icons.bar_chart_rounded), label: '分析'),
            NavigationDestination(icon: Icon(Icons.list_rounded), label: '数据'),
            NavigationDestination(icon: Icon(Icons.account_tree_rounded), label: '导图'),
            NavigationDestination(icon: Icon(Icons.notifications_rounded), label: '订阅'),
          ],
        ),
      ),
    );
  }
}
