import 'package:flutter/material.dart';
import 'package:trendpulse/models/analysis_result.dart';

/// 观点卡片 - Apple 分组列表风格
class OpinionCardsWidget extends StatelessWidget {
  final List<Opinion> opinions;
  const OpinionCardsWidget({super.key, required this.opinions});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Padding(
          padding: EdgeInsets.only(left: 4, bottom: 8),
          child: Text('核心观点', style: TextStyle(fontSize: 13, color: Color(0xFF8E8E93), fontWeight: FontWeight.w500)),
        ),
        Container(
          decoration: BoxDecoration(
            color: const Color(0xFF1C1C1E),
            borderRadius: BorderRadius.circular(13),
          ),
          child: Column(
            children: [
              for (var i = 0; i < opinions.length; i++) ...[
                if (i > 0) const Divider(height: 0.33, indent: 52, color: Color(0xFF38383A)),
                _OpinionRow(index: i + 1, opinion: opinions[i]),
              ],
            ],
          ),
        ),
      ],
    );
  }
}

class _OpinionRow extends StatelessWidget {
  final int index;
  final Opinion opinion;
  const _OpinionRow({required this.index, required this.opinion});

  @override
  Widget build(BuildContext context) {
    const colors = [Color(0xFF0A84FF), Color(0xFFBF5AF2), Color(0xFF30D158)];
    final color = colors[(index - 1) % colors.length];

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Container(
            width: 28, height: 28,
            decoration: BoxDecoration(
              color: color.withValues(alpha: 0.15),
              borderRadius: BorderRadius.circular(7),
            ),
            child: Center(
              child: Text('$index', style: TextStyle(fontSize: 14, fontWeight: FontWeight.w700, color: color)),
            ),
          ),
          const SizedBox(width: 12),
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(opinion.description, style: const TextStyle(fontSize: 15, height: 1.4)),
                const SizedBox(height: 8),
                Row(
                  children: [
                    Expanded(
                      child: ClipRRect(
                        borderRadius: BorderRadius.circular(2),
                        child: SizedBox(
                          height: 3,
                          child: LinearProgressIndicator(
                            value: opinion.supportRate / 100,
                            backgroundColor: const Color(0xFF38383A),
                            valueColor: AlwaysStoppedAnimation(color),
                          ),
                        ),
                      ),
                    ),
                    const SizedBox(width: 8),
                    Text(
                      '${opinion.supportRate.toStringAsFixed(1)}%',
                      style: TextStyle(fontSize: 13, fontWeight: FontWeight.w600, color: color),
                    ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }
}
