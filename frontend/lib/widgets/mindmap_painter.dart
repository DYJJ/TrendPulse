import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:trendpulse/utils/mindmap_layout.dart';

/// 思维导图 Canvas 绘制引擎
///
/// 基于 CustomPainter 实现，接收布局后的 LayoutNode 树，
/// 在 Canvas 上绘制节点、连线和视觉效果。
/// 绘制顺序：连线 → 子节点 → 根节点 → 文本
class MindmapCanvasPainter extends CustomPainter {
  /// 布局后的根节点（包含完整子树）
  final LayoutNode root;

  /// 当前悬浮高亮的节点（null 表示无悬浮）
  final LayoutNode? hoveredNode;

  MindmapCanvasPainter({required this.root, this.hoveredNode});

  // ---- 配色常量 ----
  static const _accentBlue = Color(0xFF0A84FF);
  static const _accentPurple = Color(0xFF5E5CE6);
  static const _borderGray = Color(0xFF38383A);
  static const _cardDark = Color(0xFF1C1C1E);
  static const _cardDeep = Color(0xFF2C2C2E);
  static const _textMuted = Color(0xFF8E8E93);

  @override
  void paint(Canvas canvas, Size size) {
    // 1. 绘制所有连线（底层）
    _paintConnections(canvas, root);
    // 2. 绘制所有子节点卡片
    _paintChildNodes(canvas, root);
    // 3. 绘制根节点（顶层，带光晕）
    _paintRootNode(canvas, root);
    // 4. 绘制悬浮高亮效果
    if (hoveredNode != null) {
      _paintHoverHighlight(canvas, hoveredNode!);
    }
    // 5. 绘制所有文本
    _paintAllText(canvas, root);
  }

  // ==================== 连线绘制 ====================

  /// 递归绘制父节点到子节点的贝塞尔曲线连线
  void _paintConnections(Canvas canvas, LayoutNode node) {
    for (final child in node.children) {
      _paintCurve(canvas, node, child);
      // 递归绘制子节点的连线
      _paintConnections(canvas, child);
    }
  }

  /// 绘制单条贝塞尔曲线连线
  ///
  /// 颜色随层级渐变：浅层 #0A84FF → 深层 #38383A
  /// 线宽随层级递减：2px → 1px
  void _paintCurve(Canvas canvas, LayoutNode parent, LayoutNode child) {
    final maxDepth = 4.0;
    final t = (child.depth / maxDepth).clamp(0.0, 1.0);
    final color = Color.lerp(_accentBlue, _borderGray, t)!;
    final strokeWidth = ui.lerpDouble(2.5, 1.5, t)!;

    final paint = Paint()
      ..color = color
      ..strokeWidth = strokeWidth
      ..style = PaintingStyle.stroke
      ..isAntiAlias = true;

    final start = parent.position;
    final end = child.position;

    // 三次贝塞尔曲线：控制点沿连线方向偏移
    final dx = end.dx - start.dx;
    final dy = end.dy - start.dy;
    final cp1 = Offset(start.dx + dx * 0.4, start.dy + dy * 0.1);
    final cp2 = Offset(start.dx + dx * 0.6, start.dy + dy * 0.9);

    final path = Path()
      ..moveTo(start.dx, start.dy)
      ..cubicTo(cp1.dx, cp1.dy, cp2.dx, cp2.dy, end.dx, end.dy);

    canvas.drawPath(path, paint);
  }

  // ==================== 子节点绘制 ====================

  /// 递归绘制所有子节点卡片（不含根节点）
  void _paintChildNodes(Canvas canvas, LayoutNode node) {
    for (final child in node.children) {
      _paintNodeCard(canvas, child);
      _paintChildNodes(canvas, child);
    }
  }

  /// 绘制子节点卡片
  ///
  /// 一级节点：#1C1C1E 填充 + #38383A 描边，圆角 12px
  /// 深层节点：#2C2C2E alpha 0.6 填充，圆角 10px
  void _paintNodeCard(Canvas canvas, LayoutNode node) {
    final rect = _nodeRect(node);

    if (node.depth == 1) {
      // 一级节点：实心卡片 + 描边
      final radius = BorderRadius.circular(14.0);
      final rrect = radius.toRRect(rect);

      // 填充
      canvas.drawRRect(
        rrect,
        Paint()
          ..color = _cardDark
          ..style = PaintingStyle.fill,
      );
      // 描边
      canvas.drawRRect(
        rrect,
        Paint()
          ..color = _borderGray
          ..style = PaintingStyle.stroke
          ..strokeWidth = 1.0,
      );
    } else {
      // 深层节点：半透明卡片
      final radius = BorderRadius.circular(12.0);
      final rrect = radius.toRRect(rect);

      canvas.drawRRect(
        rrect,
        Paint()
          ..color = _cardDeep.withAlpha(170)
          ..style = PaintingStyle.fill,
      );
    }
  }

  // ==================== 根节点绘制 ====================

  /// 绘制根节点：渐变填充 + 发光光晕
  void _paintRootNode(Canvas canvas, LayoutNode node) {
    final rect = _nodeRect(node);
    final rrect = BorderRadius.circular(18.0).toRRect(rect);

    // 发光光晕
    final glowPaint = Paint()
      ..color = _accentBlue.withAlpha(90)
      ..maskFilter = const MaskFilter.blur(BlurStyle.outer, 28);
    canvas.drawRRect(rrect, glowPaint);

    // 线性渐变填充 #0A84FF → #5E5CE6
    final gradientPaint = Paint()
      ..shader = ui.Gradient.linear(
        rect.topLeft,
        rect.bottomRight,
        [_accentBlue, _accentPurple],
      )
      ..style = PaintingStyle.fill;
    canvas.drawRRect(rrect, gradientPaint);
  }

  // ==================== 文本绘制 ====================

  /// 递归绘制所有节点的文本
  void _paintAllText(Canvas canvas, LayoutNode node) {
    _paintText(canvas, node);
    for (final child in node.children) {
      _paintAllText(canvas, child);
    }
  }

  /// 绘制单个节点的文本
  ///
  /// 根据层级使用不同字号和字重：
  /// - 根节点：白色 16px w700
  /// - 一级节点：白色 14px w500
  /// - 深层节点：#8E8E93 13px w400
  void _paintText(Canvas canvas, LayoutNode node) {
    final depth = node.depth;
    final Color textColor;
    final double fontSize;
    final FontWeight fontWeight;

    if (depth == 0) {
      textColor = Colors.white;
      fontSize = 20.0;
      fontWeight = FontWeight.w700;
    } else if (depth == 1) {
      textColor = Colors.white;
      fontSize = 17.0;
      fontWeight = FontWeight.w500;
    } else {
      textColor = _textMuted;
      fontSize = 15.0;
      fontWeight = FontWeight.w400;
    }

    final textPainter = TextPainter(
      text: TextSpan(
        text: node.data.label,
        style: TextStyle(
          color: textColor,
          fontSize: fontSize,
          fontWeight: fontWeight,
        ),
      ),
      textDirection: TextDirection.ltr,
      textAlign: TextAlign.center,
      maxLines: 10,
    );

    // 限制文本宽度在节点宽度内（留出内边距）
    final maxTextWidth = node.size.width - 20.0;
    textPainter.layout(maxWidth: maxTextWidth > 0 ? maxTextWidth : 80.0);

    // 文本居中于节点
    final textOffset = Offset(
      node.position.dx - textPainter.width / 2,
      node.position.dy - textPainter.height / 2,
    );

    textPainter.paint(canvas, textOffset);
  }

  // ==================== 工具方法 ====================

  /// 根据节点的 position（中心）和 size 计算边界矩形
  Rect _nodeRect(LayoutNode node) {
    return Rect.fromCenter(
      center: node.position,
      width: node.size.width,
      height: node.size.height,
    );
  }

  /// 绘制悬浮高亮效果
  ///
  /// 在悬浮节点周围绘制发光边框，提供视觉反馈
  void _paintHoverHighlight(Canvas canvas, LayoutNode node) {
    final rect = _nodeRect(node);
    final radius = node.depth == 0 ? 18.0 : (node.depth == 1 ? 14.0 : 12.0);
    final rrect = BorderRadius.circular(radius).toRRect(rect);

    // 外发光
    final glowPaint = Paint()
      ..color = _accentBlue.withAlpha(60)
      ..maskFilter = const MaskFilter.blur(BlurStyle.outer, 12);
    canvas.drawRRect(rrect, glowPaint);

    // 高亮描边
    final borderPaint = Paint()
      ..color = _accentBlue.withAlpha(180)
      ..style = PaintingStyle.stroke
      ..strokeWidth = 2.0;
    canvas.drawRRect(rrect, borderPaint);
  }

  @override
  bool shouldRepaint(covariant MindmapCanvasPainter oldDelegate) {
    return oldDelegate.root != root || oldDelegate.hoveredNode != hoveredNode;
  }
}


/// 带变换的思维导图绘制器
///
/// 在 Canvas 层面应用平移和缩放变换，
/// 这样 CustomPaint 的 size 就是视口大小，
/// 手势命中区域始终覆盖整个视口。
class TransformedMindmapPainter extends CustomPainter {
  final LayoutNode root;
  final LayoutNode? hoveredNode;
  final double scale;
  final Offset offset;

  /// 内部委托给 MindmapCanvasPainter 做实际绘制
  late final MindmapCanvasPainter _delegate;

  TransformedMindmapPainter({
    required this.root,
    this.hoveredNode,
    required this.scale,
    required this.offset,
  }) {
    _delegate = MindmapCanvasPainter(root: root, hoveredNode: hoveredNode);
  }

  @override
  void paint(Canvas canvas, Size size) {
    // 先裁剪到视口范围
    canvas.clipRect(Rect.fromLTWH(0, 0, size.width, size.height));
    // 应用平移和缩放变换
    canvas.translate(offset.dx, offset.dy);
    canvas.scale(scale);
    // 委托绘制
    _delegate.paint(canvas, size);
  }

  @override
  bool shouldRepaint(covariant TransformedMindmapPainter oldDelegate) {
    return oldDelegate.root != root ||
        oldDelegate.hoveredNode != hoveredNode ||
        oldDelegate.scale != scale ||
        oldDelegate.offset != offset;
  }
}
