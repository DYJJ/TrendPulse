import 'dart:math';
import 'dart:ui';

import 'package:flutter/painting.dart';
import 'package:trendpulse/utils/mindmap_parser.dart';

/// 布局计算后的节点，包含位置和尺寸信息
class LayoutNode {
  /// 原始节点数据
  final MindmapNode data;

  /// 节点中心坐标
  Offset position;

  /// 节点尺寸（宽 x 高）
  Size size;

  /// 子节点列表
  final List<LayoutNode> children;

  /// 深度层级（同 MindmapNode.level）
  final int depth;

  LayoutNode({
    required this.data,
    this.position = Offset.zero,
    this.size = Size.zero,
    required this.children,
    required this.depth,
  });
}

/// 将扁平 MindmapNode 列表转换为树形 LayoutNode 结构
///
/// 使用栈结构按 level 关系建立父子关系。
/// 处理边界情况：空列表返回 null，无根节点时将第一个节点视为根节点。
LayoutNode? buildTree(List<MindmapNode> nodes) {
  if (nodes.isEmpty) return null;

  // 确保第一个节点作为根节点
  final rootData = nodes.first;
  final root = LayoutNode(
    data: rootData,
    children: [],
    depth: rootData.level,
  );

  if (nodes.length == 1) return root;

  // 栈结构：存储 (LayoutNode, level) 用于追踪父子关系
  final stack = <LayoutNode>[root];

  for (var i = 1; i < nodes.length; i++) {
    final node = nodes[i];
    final layoutNode = LayoutNode(
      data: node,
      children: [],
      depth: node.level,
    );

    // 弹出栈中 level >= 当前节点的元素，找到父节点
    while (stack.length > 1 && stack.last.depth >= node.level) {
      stack.removeLast();
    }

    // 栈顶即为父节点
    stack.last.children.add(layoutNode);
    stack.add(layoutNode);
  }

  return root;
}


/// 思维导图布局引擎
///
/// 将扁平的 MindmapNode 列表转换为带位置信息的树形 LayoutNode 结构。
/// 采用径向布局算法：根节点居中，子节点环绕分布。
class MindmapLayoutEngine {
  /// 节点间径向间距
  final double radialGap;

  /// 节点间最小间距
  final double minSpacing;

  /// 节点最大宽度
  final double maxNodeWidth;

  /// 节点内边距
  final double nodePadding;

  MindmapLayoutEngine({
    this.radialGap = 180.0,
    this.minSpacing = 30.0,
    this.maxNodeWidth = 240.0,
    this.nodePadding = 20.0,
  });

  /// 将扁平节点列表构建为树形结构并计算布局
  ///
  /// 返回根 LayoutNode（包含完整的子树）和画布总尺寸。
  /// 如果节点列表为空，返回 null。
  (LayoutNode root, Size canvasSize)? layout(
    List<MindmapNode> nodes,
    Size canvasSize,
  ) {
    final tree = buildTree(nodes);
    if (tree == null) return null;

    // 第一步：计算所有节点的尺寸
    _computeSizes(tree);

    // 第二步：径向布局 - 根节点居中
    final center = Offset(canvasSize.width / 2, canvasSize.height / 2);
    tree.position = center;

    // 第三步：布局子节点
    if (tree.children.isNotEmpty) {
      _layoutChildren(tree, center, canvasSize);
    }

    // 第四步：碰撞检测和调整
    _resolveCollisions(tree);

    return (tree, canvasSize);
  }

  /// 计算节点尺寸（基于文本内容）
  ///
  /// 使用 TextPainter 测量文本宽高，支持自动换行。
  void _computeSizes(LayoutNode node) {
    node.size = _measureNodeSize(node.data.label, node.depth);
    for (final child in node.children) {
      _computeSizes(child);
    }
  }

  /// 测量单个节点的尺寸
  ///
  /// 根据层级使用不同字号，文本超出最大宽度时自动换行。
  Size _measureNodeSize(String text, int depth) {
    final fontSize = _fontSizeForDepth(depth);
    final fontWeight = _fontWeightForDepth(depth);

    final textPainter = TextPainter(
      text: TextSpan(
        text: text,
        style: TextStyle(fontSize: fontSize, fontWeight: fontWeight),
      ),
      textDirection: TextDirection.ltr,
      maxLines: 10,
    );

    // 先不限宽度测量，看文本自然宽度
    textPainter.layout(maxWidth: double.infinity);
    final naturalWidth = textPainter.width;

    // 如果自然宽度超过最大宽度，启用换行
    final constrainedWidth = min(naturalWidth, maxNodeWidth - nodePadding * 2);
    textPainter.layout(maxWidth: constrainedWidth);

    final width = textPainter.width + nodePadding * 2;
    final height = textPainter.height + nodePadding * 1.5;

    // 确保最小尺寸
    return Size(
      max(width, 80.0),
      max(height, 44.0),
    );
  }

  /// 根据层级返回字号
  double _fontSizeForDepth(int depth) {
    if (depth == 0) return 20.0;
    if (depth == 1) return 17.0;
    return 15.0;
  }

  /// 根据层级返回字重
  FontWeight _fontWeightForDepth(int depth) {
    if (depth == 0) return FontWeight.w700;
    if (depth == 1) return FontWeight.w500;
    return FontWeight.w400;
  }

  /// 径向布局子节点
  ///
  /// 一级子节点均匀分布在根节点周围，深层节点沿径向延伸。
  void _layoutChildren(
    LayoutNode parent,
    Offset center,
    Size canvasSize,
  ) {
    if (parent.children.isEmpty) return;

    final childCount = parent.children.length;

    if (parent.depth == 0) {
      // 一级子节点：均匀环绕根节点
      _layoutFirstLevel(parent, center, canvasSize);
    } else {
      // 深层子节点：沿父节点的径向方向扇形展开
      _layoutDeeperLevel(parent, center);
    }
  }

  /// 布局一级子节点（均匀环绕根节点）
  void _layoutFirstLevel(
    LayoutNode root,
    Offset center,
    Size canvasSize,
  ) {
    final childCount = root.children.length;
    // 计算基础半径：根据画布尺寸和子节点数量动态调整
    final baseRadius = min(canvasSize.width, canvasSize.height) * 0.3;
    final radius = max(baseRadius, radialGap * 1.5);

    // 起始角度从顶部开始（-π/2），均匀分配
    final angleStep = 2 * pi / childCount;
    final startAngle = -pi / 2;

    for (var i = 0; i < childCount; i++) {
      final child = root.children[i];
      final angle = startAngle + angleStep * i;

      child.position = Offset(
        center.dx + radius * cos(angle),
        center.dy + radius * sin(angle),
      );

      // 递归布局更深层级的子节点
      if (child.children.isNotEmpty) {
        _layoutDeeperLevel(child, center);
      }
    }
  }

  /// 布局深层子节点（沿径向方向扇形展开）
  void _layoutDeeperLevel(LayoutNode parent, Offset rootCenter) {
    if (parent.children.isEmpty) return;

    final childCount = parent.children.length;

    // 计算父节点相对于根节点的角度
    final parentAngle = atan2(
      parent.position.dy - rootCenter.dy,
      parent.position.dx - rootCenter.dx,
    );

    // 子节点沿父节点方向延伸，扇形展开
    final spreadAngle = min(pi / 3, pi / max(childCount, 1));
    final totalSpread = spreadAngle * (childCount - 1);
    final startAngle = parentAngle - totalSpread / 2;

    // 深层节点的径向距离递减
    final distance = radialGap * 0.9;

    for (var i = 0; i < childCount; i++) {
      final child = parent.children[i];
      final angle = childCount == 1
          ? parentAngle
          : startAngle + spreadAngle * i;

      child.position = Offset(
        parent.position.dx + distance * cos(angle),
        parent.position.dy + distance * sin(angle),
      );

      // 递归布局
      if (child.children.isNotEmpty) {
        _layoutDeeperLevel(child, rootCenter);
      }
    }
  }

  /// 碰撞检测和间距调整
  ///
  /// 收集所有节点，检查任意两个节点是否重叠，
  /// 如果重叠则根据实际重叠量沿连线方向推开。
  void _resolveCollisions(LayoutNode root) {
    final allNodes = <LayoutNode>[];
    _collectNodes(root, allNodes);

    // 多轮迭代解决碰撞（最多 50 轮）
    for (var iteration = 0; iteration < 50; iteration++) {
      var hasCollision = false;

      for (var i = 0; i < allNodes.length; i++) {
        for (var j = i + 1; j < allNodes.length; j++) {
          final a = allNodes[i];
          final b = allNodes[j];

          final overlap = _overlapAmount(a, b);
          if (overlap > 0) {
            hasCollision = true;
            _pushApart(a, b, root, overlap);
          }
        }
      }

      if (!hasCollision) break;
    }
  }

  /// 计算两个节点的重叠量
  ///
  /// 返回值 > 0 表示存在重叠，值为需要推开的最小距离。
  /// 返回值 <= 0 表示无重叠。
  double _overlapAmount(LayoutNode a, LayoutNode b) {
    final halfWidthA = (a.size.width + minSpacing) / 2;
    final halfHeightA = (a.size.height + minSpacing) / 2;
    final halfWidthB = (b.size.width + minSpacing) / 2;
    final halfHeightB = (b.size.height + minSpacing) / 2;

    final dx = (b.position.dx - a.position.dx).abs();
    final dy = (b.position.dy - a.position.dy).abs();

    final overlapX = halfWidthA + halfWidthB - dx;
    final overlapY = halfHeightA + halfHeightB - dy;

    // 两个轴都有重叠才算真正重叠
    if (overlapX > 0 && overlapY > 0) {
      return min(overlapX, overlapY);
    }
    return 0;
  }

  /// 将两个重叠节点推开
  ///
  /// 根据实际重叠量计算推开距离，不移动根节点。
  void _pushApart(LayoutNode a, LayoutNode b, LayoutNode root, double overlap) {
    var dx = b.position.dx - a.position.dx;
    var dy = b.position.dy - a.position.dy;
    final dist = sqrt(dx * dx + dy * dy);

    // 如果两个节点完全重合，给一个随机方向
    if (dist < 0.01) {
      dx = 1.0;
      dy = 0.0;
    } else {
      dx /= dist;
      dy /= dist;
    }

    // 推开距离 = 重叠量的一半 + 额外间距，确保一次推开足够
    final pushDistance = overlap / 2 + minSpacing * 0.25;

    // 不移动根节点
    if (a.data.isRoot || a.depth == 0) {
      b.position = Offset(
        b.position.dx + dx * pushDistance * 2,
        b.position.dy + dy * pushDistance * 2,
      );
    } else if (b.data.isRoot || b.depth == 0) {
      a.position = Offset(
        a.position.dx - dx * pushDistance * 2,
        a.position.dy - dy * pushDistance * 2,
      );
    } else {
      // 两个都不是根节点，各推一半
      a.position = Offset(
        a.position.dx - dx * pushDistance,
        a.position.dy - dy * pushDistance,
      );
      b.position = Offset(
        b.position.dx + dx * pushDistance,
        b.position.dy + dy * pushDistance,
      );
    }
  }

  /// 递归收集所有节点到列表中
  void _collectNodes(LayoutNode node, List<LayoutNode> result) {
    result.add(node);
    for (final child in node.children) {
      _collectNodes(child, result);
    }
  }
}

/// 计算使导图适配视口的自适应缩放比例
///
/// 根据画布尺寸和视口尺寸计算最佳缩放比例，
/// 使整个思维导图刚好适配视口可见区域。
/// 缩放比例限制在 [0.3, 3.0] 范围内。
double calculateFitScale(Size canvasSize, Size viewportSize) {
  // 画布或视口尺寸无效时返回默认缩放 1.0
  if (canvasSize.width <= 0 ||
      canvasSize.height <= 0 ||
      viewportSize.width <= 0 ||
      viewportSize.height <= 0) {
    return 1.0;
  }

  // 分别计算水平和垂直方向的缩放比例
  final scaleX = viewportSize.width / canvasSize.width;
  final scaleY = viewportSize.height / canvasSize.height;

  // 取较小值确保两个方向都能完整显示
  final scale = min(scaleX, scaleY);

  // 限制在 0.3 - 3.0 范围内
  return scale.clamp(0.3, 3.0);
}

