import 'package:flutter/material.dart';
import 'dart:math' as math;

/// 舆情热度 - Apple 风格圆环卡片
class HeatScoreWidget extends StatelessWidget {
  final double heatScore;
  const HeatScoreWidget({super.key, required this.heatScore});

  @override
  Widget build(BuildContext context) {
    final norm = (heatScore / 100).clamp(0.0, 1.0);
    final color = heatScore < 30
        ? const Color(0xFF0A84FF)
        : heatScore < 60
            ? const Color(0xFFFF9F0A)
            : const Color(0xFFFF453A);

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
            child: Text('热度', style: TextStyle(fontSize: 13, color: Color(0xFF8E8E93))),
          ),
          const SizedBox(height: 12),
          SizedBox(
            width: 80, height: 80,
            child: CustomPaint(
              painter: _AppleRingPainter(progress: norm, color: color),
              child: Center(
                child: Text(
                  heatScore.toStringAsFixed(0),
                  style: TextStyle(fontSize: 24, fontWeight: FontWeight.w700, color: color),
                ),
              ),
            ),
          ),
          const SizedBox(height: 8),
          Text(
            heatScore < 30 ? '低' : heatScore < 60 ? '中' : '高',
            style: TextStyle(fontSize: 13, fontWeight: FontWeight.w500, color: color),
          ),
        ],
      ),
    );
  }
}

class _AppleRingPainter extends CustomPainter {
  final double progress;
  final Color color;
  _AppleRingPainter({required this.progress, required this.color});

  @override
  void paint(Canvas canvas, Size size) {
    final c = Offset(size.width / 2, size.height / 2);
    final r = size.width / 2 - 5;
    // 背景环
    canvas.drawCircle(c, r, Paint()
      ..color = color.withValues(alpha: 0.15)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 7
      ..strokeCap = StrokeCap.round);
    // 进度环
    canvas.drawArc(
      Rect.fromCircle(center: c, radius: r),
      -math.pi / 2,
      2 * math.pi * progress,
      false,
      Paint()
        ..color = color
        ..style = PaintingStyle.stroke
        ..strokeWidth = 7
        ..strokeCap = StrokeCap.round,
    );
  }

  @override
  bool shouldRepaint(covariant _AppleRingPainter old) => old.progress != progress;
}
