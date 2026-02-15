import 'package:flutter/material.dart';

/// AI 摘要 - Apple 卡片风格
class SummaryWidget extends StatelessWidget {
  final String summary;
  const SummaryWidget({super.key, required this.summary});

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Padding(
          padding: EdgeInsets.only(left: 4, bottom: 8),
          child: Text('AI 摘要', style: TextStyle(fontSize: 13, color: Color(0xFF8E8E93), fontWeight: FontWeight.w500)),
        ),
        Container(
          width: double.infinity,
          padding: const EdgeInsets.all(16),
          decoration: BoxDecoration(
            color: const Color(0xFF1C1C1E),
            borderRadius: BorderRadius.circular(13),
          ),
          child: Text(
            summary,
            style: const TextStyle(fontSize: 15, height: 1.65, color: Color(0xFFEBEBF5)),
          ),
        ),
      ],
    );
  }
}
