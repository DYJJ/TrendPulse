import 'package:flutter/material.dart';
import 'package:trendpulse/utils/sentiment_colors.dart';

/// 情感仪表盘 - Apple 风格简洁卡片
class SentimentGaugeWidget extends StatelessWidget {
  final double sentimentScore;
  final String sentimentLabel;

  const SentimentGaugeWidget({
    super.key,
    required this.sentimentScore,
    required this.sentimentLabel,
  });

  @override
  Widget build(BuildContext context) {
    final color = SentimentColors.getColor(sentimentScore);
    final label = SentimentColors.getLabelText(sentimentLabel);

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF1C1C1E),
        borderRadius: BorderRadius.circular(13),
      ),
      child: Column(
        children: [
          const Align(
            alignment: Alignment.centerLeft,
            child: Text('情感', style: TextStyle(fontSize: 13, color: Color(0xFF8E8E93))),
          ),
          const SizedBox(height: 12),
          Text(
            sentimentScore.toStringAsFixed(1),
            style: TextStyle(fontSize: 34, fontWeight: FontWeight.w700, color: color, height: 1),
          ),
          const SizedBox(height: 6),
          Container(
            padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 3),
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.15),
              borderRadius: BorderRadius.circular(6),
            ),
            child: Text(label, style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: color)),
          ),
          const SizedBox(height: 12),
          // 进度条
          ClipRRect(
            borderRadius: BorderRadius.circular(2),
            child: SizedBox(
              height: 4,
              child: LinearProgressIndicator(
                value: sentimentScore / 100,
                backgroundColor: const Color(0xFF38383A),
                valueColor: AlwaysStoppedAnimation(color),
              ),
            ),
          ),
          const SizedBox(height: 4),
          const Row(
            mainAxisAlignment: MainAxisAlignment.spaceBetween,
            children: [
              Text('负面', style: TextStyle(fontSize: 10, color: Color(0xFF636366))),
              Text('正面', style: TextStyle(fontSize: 10, color: Color(0xFF636366))),
            ],
          ),
        ],
      ),
    );
  }
}
