import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:trendpulse/providers/analysis_provider.dart';
import 'package:trendpulse/widgets/heat_score_widget.dart';
import 'package:trendpulse/widgets/opinion_cards_widget.dart';
import 'package:trendpulse/widgets/sentiment_gauge_widget.dart';
import 'package:trendpulse/widgets/summary_widget.dart';

/// 仪表盘页面 - Apple 大标题风格
class DashboardPage extends StatelessWidget {
  const DashboardPage({super.key});

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<AnalysisProvider>();
    final result = provider.result;

    return Scaffold(
      body: result == null
          ? _buildEmpty(context, provider)
          : CustomScrollView(
              slivers: [
                const SliverToBoxAdapter(child: SizedBox(height: 60)),
                SliverToBoxAdapter(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 20),
                    child: Text('分析', style: Theme.of(context).textTheme.displayLarge),
                  ),
                ),
                const SliverToBoxAdapter(child: SizedBox(height: 20)),
                // 指标卡片
                SliverToBoxAdapter(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 20),
                    child: Row(
                      children: [
                        Expanded(child: HeatScoreWidget(heatScore: result.heatScore)),
                        const SizedBox(width: 12),
                        Expanded(child: SentimentGaugeWidget(
                          sentimentScore: result.sentimentScore,
                          sentimentLabel: result.sentimentLabel,
                        )),
                      ],
                    ),
                  ),
                ),
                const SliverToBoxAdapter(child: SizedBox(height: 20)),
                // 观点
                if (result.opinions.isNotEmpty)
                  SliverToBoxAdapter(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 20),
                      child: OpinionCardsWidget(opinions: result.opinions),
                    ),
                  ),
                const SliverToBoxAdapter(child: SizedBox(height: 16)),
                // 摘要
                if (result.summary.isNotEmpty)
                  SliverToBoxAdapter(
                    child: Padding(
                      padding: const EdgeInsets.symmetric(horizontal: 20),
                      child: SummaryWidget(summary: result.summary),
                    ),
                  ),
                const SliverToBoxAdapter(child: SizedBox(height: 40)),
              ],
            ),
    );
  }

  Widget _buildEmpty(BuildContext context, AnalysisProvider provider) {
    if (provider.isLoading) {
      return const Center(child: CircularProgressIndicator.adaptive());
    }
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.bar_chart_rounded, size: 56, color: const Color(0xFF8E8E93).withValues(alpha: 0.3)),
          const SizedBox(height: 16),
          const Text('暂无分析结果', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600, color: Color(0xFF8E8E93))),
          const SizedBox(height: 6),
          const Text('在搜索页面发起采集任务', style: TextStyle(fontSize: 15, color: Color(0xFF636366))),
        ],
      ),
    );
  }
}
