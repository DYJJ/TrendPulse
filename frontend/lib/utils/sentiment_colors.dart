import 'package:flutter/material.dart';

/// 情感分数颜色映射 - Apple 系统色
class SentimentColors {
  SentimentColors._();

  static Color getColor(double score) {
    if (score <= 30) return const Color(0xFFFF453A); // 红
    if (score <= 70) return const Color(0xFFFF9F0A); // 橙
    return const Color(0xFF30D158); // 绿
  }

  static String getLabelText(String label) {
    switch (label) {
      case 'negative': return '负面';
      case 'neutral': return '中性';
      case 'positive': return '正面';
      default: return label;
    }
  }
}
