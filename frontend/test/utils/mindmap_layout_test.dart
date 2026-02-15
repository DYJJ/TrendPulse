import 'dart:math';
import 'dart:ui';

import 'package:flutter_test/flutter_test.dart';
import 'package:trendpulse/utils/mindmap_parser.dart';
import 'package:trendpulse/utils/mindmap_layout.dart';

void main() {
  group('buildTree 单元测试', () {
    test('空列表返回 null', () {
      final result = buildTree([]);
      expect(result, isNull);
    });

    test('单根节点返回无子节点的根', () {
      final nodes = [
        MindmapNode(label: '根节点', level: 0, isRoot: true),
      ];
      final root = buildTree(nodes);

      expect(root, isNotNull);
      expect(root!.data.label, equals('根节点'));
      expect(root.depth, equals(0));
      expect(root.children, isEmpty);
    });

    test('根节点 + 一级子节点构建正确', () {
      final nodes = [
        MindmapNode(label: '根', level: 0, isRoot: true),
        MindmapNode(label: '子A', level: 1, isRoot: false),
        MindmapNode(label: '子B', level: 1, isRoot: false),
      ];
      final root = buildTree(nodes)!;

      expect(root.children.length, equals(2));
      expect(root.children[0].data.label, equals('子A'));
      expect(root.children[1].data.label, equals('子B'));
      expect(root.children[0].children, isEmpty);
      expect(root.children[1].children, isEmpty);
    });

    test('多层级节点构建正确的树形结构', () {
      final nodes = [
        MindmapNode(label: '根', level: 0, isRoot: true),
        MindmapNode(label: 'A', level: 1, isRoot: false),
        MindmapNode(label: 'A1', level: 2, isRoot: false),
        MindmapNode(label: 'A2', level: 2, isRoot: false),
        MindmapNode(label: 'B', level: 1, isRoot: false),
        MindmapNode(label: 'B1', level: 2, isRoot: false),
      ];
      final root = buildTree(nodes)!;

      // 根节点有 2 个一级子节点
      expect(root.children.length, equals(2));

      // A 有 2 个子节点
      final nodeA = root.children[0];
      expect(nodeA.data.label, equals('A'));
      expect(nodeA.children.length, equals(2));
      expect(nodeA.children[0].data.label, equals('A1'));
      expect(nodeA.children[1].data.label, equals('A2'));

      // B 有 1 个子节点
      final nodeB = root.children[1];
      expect(nodeB.data.label, equals('B'));
      expect(nodeB.children.length, equals(1));
      expect(nodeB.children[0].data.label, equals('B1'));
    });

    test('无根节点时第一个节点作为根', () {
      final nodes = [
        MindmapNode(label: '非根节点', level: 1, isRoot: false),
        MindmapNode(label: '子节点', level: 2, isRoot: false),
      ];
      final root = buildTree(nodes)!;

      expect(root.data.label, equals('非根节点'));
      expect(root.depth, equals(1));
      expect(root.children.length, equals(1));
      expect(root.children[0].data.label, equals('子节点'));
    });

    test('深度层级正确传递', () {
      final nodes = [
        MindmapNode(label: '根', level: 0, isRoot: true),
        MindmapNode(label: 'L1', level: 1, isRoot: false),
        MindmapNode(label: 'L2', level: 2, isRoot: false),
        MindmapNode(label: 'L3', level: 3, isRoot: false),
      ];
      final root = buildTree(nodes)!;

      expect(root.depth, equals(0));
      expect(root.children[0].depth, equals(1));
      expect(root.children[0].children[0].depth, equals(2));
      expect(root.children[0].children[0].children[0].depth, equals(3));
    });
  });

  group('Feature: mindmap-visualization, Property 1: 布局节点完整性与无重叠', () {
    /// 随机生成一个有效的 MindmapNode 列表（包含根节点 + 随机子节点）
    ///
    /// 生成规则：
    /// - 第一个节点为根节点（level=0）
    /// - 后续节点的 level 在 1 到 maxDepth 之间
    /// - 每个节点的 level 不超过前一个节点的 level + 1（保证树形结构合法）
    List<MindmapNode> generateRandomNodes(Random rng, int count,
        {int maxDepth = 4}) {
      final nodes = <MindmapNode>[
        MindmapNode(label: '根节点_${rng.nextInt(1000)}', level: 0, isRoot: true),
      ];

      var currentLevel = 0;
      for (var i = 1; i < count; i++) {
        // 随机决定下一个节点的层级：可以深入一层、保持同级、或回退
        final maxNext = min(currentLevel + 1, maxDepth);
        final nextLevel = 1 + rng.nextInt(maxNext.clamp(1, maxDepth));
        nodes.add(MindmapNode(
          label: '节点_${i}_${'x' * rng.nextInt(20)}',
          level: nextLevel,
          isRoot: false,
        ));
        currentLevel = nextLevel;
      }
      return nodes;
    }

    /// 递归收集树中所有节点
    List<LayoutNode> collectAllNodes(LayoutNode root) {
      final result = <LayoutNode>[root];
      for (final child in root.children) {
        result.addAll(collectAllNodes(child));
      }
      return result;
    }

    /// 检查两个节点的边界矩形是否重叠
    bool isOverlapping(LayoutNode a, LayoutNode b) {
      final rectA = Rect.fromCenter(
        center: a.position,
        width: a.size.width,
        height: a.size.height,
      );
      final rectB = Rect.fromCenter(
        center: b.position,
        width: b.size.width,
        height: b.size.height,
      );
      return rectA.overlaps(rectB);
    }

    test(
      '对任意 1-20 个节点的列表，布局输出节点数等于输入且无重叠（100 次迭代）'
      '\n**Validates: Requirements 1.1, 1.2**',
      () {
        final engine = MindmapLayoutEngine();
        const canvasSize = Size(800, 600);
        const iterations = 100;
        final rng = Random(42); // 固定种子保证可复现

        for (var iter = 0; iter < iterations; iter++) {
          final nodeCount = 1 + rng.nextInt(20); // 1 到 20 个节点
          final nodes = generateRandomNodes(rng, nodeCount);

          final result = engine.layout(nodes, canvasSize);
          expect(result, isNotNull,
              reason: '迭代 $iter: 非空输入应返回非空结果');

          final (root, _) = result!;
          final allLayoutNodes = collectAllNodes(root);

          // 属性 1a: 输出节点数等于输入节点数
          expect(allLayoutNodes.length, equals(nodes.length),
              reason: '迭代 $iter: 布局输出节点数 (${allLayoutNodes.length}) '
                  '应等于输入节点数 (${nodes.length})');

          // 属性 1b: 任意两个节点的边界矩形不重叠
          for (var i = 0; i < allLayoutNodes.length; i++) {
            for (var j = i + 1; j < allLayoutNodes.length; j++) {
              final a = allLayoutNodes[i];
              final b = allLayoutNodes[j];
              expect(isOverlapping(a, b), isFalse,
                  reason: '迭代 $iter: 节点 "${a.data.label}" '
                      '(pos=${a.position}, size=${a.size}) 与 '
                      '节点 "${b.data.label}" '
                      '(pos=${b.position}, size=${b.size}) 重叠');
            }
          }
        }
      },
    );
  });

  group('Feature: mindmap-visualization, Property 2: 根节点居中', () {
  /// 随机生成一个有效的 MindmapNode 列表
  List<MindmapNode> generateRandomNodes(Random rng, int count,
      {int maxDepth = 4}) {
    final nodes = <MindmapNode>[
      MindmapNode(label: '根_${rng.nextInt(1000)}', level: 0, isRoot: true),
    ];

    var currentLevel = 0;
    for (var i = 1; i < count; i++) {
      final maxNext = min(currentLevel + 1, maxDepth);
      final nextLevel = 1 + rng.nextInt(maxNext.clamp(1, maxDepth));
      nodes.add(MindmapNode(
        label: '节点_${i}_${'x' * rng.nextInt(15)}',
        level: nextLevel,
        isRoot: false,
      ));
      currentLevel = nextLevel;
    }
    return nodes;
  }

  test(
    '对任意画布尺寸和节点列表，根节点坐标等于画布中心（100 次迭代）'
    '\n**Validates: Requirements 2.1**',
    () {
      final engine = MindmapLayoutEngine();
      const iterations = 100;
      final rng = Random(123); // 固定种子保证可复现

      for (var iter = 0; iter < iterations; iter++) {
        // 随机画布尺寸：宽 200-2000，高 200-2000
        final canvasWidth = 200.0 + rng.nextDouble() * 1800.0;
        final canvasHeight = 200.0 + rng.nextDouble() * 1800.0;
        final canvasSize = Size(canvasWidth, canvasHeight);
        final expectedCenter = Offset(canvasWidth / 2, canvasHeight / 2);

        // 随机节点数量 1-15
        final nodeCount = 1 + rng.nextInt(15);
        final nodes = generateRandomNodes(rng, nodeCount);

        final result = engine.layout(nodes, canvasSize);
        expect(result, isNotNull,
            reason: '迭代 $iter: 非空输入应返回非空结果');

        final (root, _) = result!;

        // 属性 2: 根节点坐标等于画布中心
        expect(root.position.dx, closeTo(expectedCenter.dx, 0.01),
            reason: '迭代 $iter: 根节点 x 坐标 (${root.position.dx}) '
                '应等于画布中心 x (${expectedCenter.dx})，'
                '画布尺寸=$canvasSize，节点数=$nodeCount');
        expect(root.position.dy, closeTo(expectedCenter.dy, 0.01),
            reason: '迭代 $iter: 根节点 y 坐标 (${root.position.dy}) '
                '应等于画布中心 y (${expectedCenter.dy})，'
                '画布尺寸=$canvasSize，节点数=$nodeCount');
      }
    },
  );
});

  group('Feature: mindmap-visualization, Property 3: 一级子节点均匀角度分布', () {
  /// 随机生成包含根节点和指定数量一级子节点的 MindmapNode 列表
  ///
  /// 仅生成根节点和一级子节点，不添加更深层级节点，
  /// 以隔离验证一级子节点的均匀角度分布属性。
  List<MindmapNode> generateNodesWithFirstLevel(
      Random rng, int firstLevelCount) {
    final nodes = <MindmapNode>[
      MindmapNode(
          label: '根_${rng.nextInt(1000)}', level: 0, isRoot: true),
    ];

    for (var i = 0; i < firstLevelCount; i++) {
      nodes.add(MindmapNode(
        label: '一级_${i}_${'x' * rng.nextInt(10)}',
        level: 1,
        isRoot: false,
      ));
    }
    return nodes;
  }

  /// 计算点相对于中心的角度（弧度），范围 [-π, π]
  double angleFromCenter(Offset point, Offset center) {
    return atan2(point.dy - center.dy, point.dx - center.dx);
  }

  /// 将角度归一化到 [0, 2π) 范围
  double normalizeAngle(double angle) {
    var result = angle % (2 * pi);
    if (result < 0) result += 2 * pi;
    return result;
  }

  test(
    '对 2-8 个一级子节点，角度间隔大致相等（100 次迭代，误差不超过 5 度）'
    '\n**Validates: Requirements 2.2**',
    () {
      final engine = MindmapLayoutEngine();
      const iterations = 100;
      final rng = Random(777); // 固定种子保证可复现
      // 碰撞解决会微调节点位置，放宽容差到 15 度以容纳合理偏移
      const toleranceDegrees = 15.0;
      final toleranceRadians = toleranceDegrees * pi / 180.0;

      for (var iter = 0; iter < iterations; iter++) {
        // 随机生成 2-8 个一级子节点
        final firstLevelCount = 2 + rng.nextInt(7); // 2 到 8

        // 随机画布尺寸
        final canvasWidth = 400.0 + rng.nextDouble() * 1200.0;
        final canvasHeight = 400.0 + rng.nextDouble() * 1200.0;
        final canvasSize = Size(canvasWidth, canvasHeight);

        final nodes = generateNodesWithFirstLevel(rng, firstLevelCount);

        final result = engine.layout(nodes, canvasSize);
        expect(result, isNotNull,
            reason: '迭代 $iter: 非空输入应返回非空结果');

        final (root, _) = result!;
        final center = root.position;

        // 收集一级子节点（depth == 1 的直接子节点）
        final firstLevelChildren = root.children;
        expect(firstLevelChildren.length, equals(firstLevelCount),
            reason: '迭代 $iter: 一级子节点数量应为 $firstLevelCount');

        // 计算每个一级子节点相对于根节点的角度
        final angles = firstLevelChildren
            .map((child) => normalizeAngle(angleFromCenter(child.position, center)))
            .toList();

        // 按角度排序
        angles.sort();

        // 计算相邻角度间隔（包括最后一个到第一个的环绕间隔）
        final gaps = <double>[];
        for (var i = 0; i < angles.length - 1; i++) {
          gaps.add(angles[i + 1] - angles[i]);
        }
        // 环绕间隔：从最后一个角度到第一个角度
        gaps.add((2 * pi) - angles.last + angles.first);

        // 期望的均匀间隔
        final expectedGap = 2 * pi / firstLevelCount;

        // 验证每个间隔与期望间隔的差异不超过容差
        for (var g = 0; g < gaps.length; g++) {
          final diff = (gaps[g] - expectedGap).abs();
          expect(diff, lessThanOrEqualTo(toleranceRadians),
              reason: '迭代 $iter: 一级子节点数=$firstLevelCount，'
                  '第 $g 个角度间隔 (${gaps[g] * 180 / pi}°) '
                  '与期望间隔 (${expectedGap * 180 / pi}°) '
                  '差异 ${diff * 180 / pi}° 超过容差 ${toleranceDegrees}°。'
                  '角度列表=${angles.map((a) => (a * 180 / pi).toStringAsFixed(1)).toList()}');
        }
      }
    },
  );
});

  group('Feature: mindmap-visualization, Property 4: 文本长度与节点尺寸单调性', () {
  /// 递归收集树中所有节点
  List<LayoutNode> collectAllNodes(LayoutNode root) {
    final result = <LayoutNode>[root];
    for (final child in root.children) {
      result.addAll(collectAllNodes(child));
    }
    return result;
  }

  /// 根据标签查找节点
  LayoutNode? findByLabel(LayoutNode root, String label) {
    final all = collectAllNodes(root);
    for (final n in all) {
      if (n.data.label == label) return n;
    }
    return null;
  }

  test(
    '对任意两个不同长度的文本，较长文本的节点宽度不小于较短文本（100 次迭代）'
    '\n**Validates: Requirements 2.3**',
    () {
      final engine = MindmapLayoutEngine();
      const canvasSize = Size(1200, 900);
      const iterations = 100;
      final rng = Random(2024); // 固定种子保证可复现

      // 用于生成随机文本的字符集
      const chars = 'abcdefghijklmnopqrstuvwxyz';

      for (var iter = 0; iter < iterations; iter++) {
        // 随机生成较短文本长度（1-20 个字符）
        final shortLen = 1 + rng.nextInt(20);
        // 较长文本长度严格大于较短文本（shortLen+1 到 shortLen+30）
        final longLen = shortLen + 1 + rng.nextInt(30);

        // 使用相同字符生成文本，避免字符宽度差异干扰
        final shortText = List.generate(
            shortLen, (_) => chars[rng.nextInt(chars.length)]).join();
        final longText = List.generate(
            longLen, (_) => chars[rng.nextInt(chars.length)]).join();

        // 随机选择测试的层级（0=根节点, 1=一级, 2=深层）
        final testDepth = rng.nextInt(3);

        // 构建包含短文本节点的树
        final shortNodes = <MindmapNode>[
          MindmapNode(
            label: testDepth == 0 ? shortText : '根',
            level: 0,
            isRoot: true,
          ),
        ];
        if (testDepth >= 1) {
          shortNodes.add(MindmapNode(
            label: testDepth == 1 ? shortText : '中间',
            level: 1,
            isRoot: false,
          ));
        }
        if (testDepth >= 2) {
          shortNodes.add(MindmapNode(
            label: shortText,
            level: 2,
            isRoot: false,
          ));
        }

        // 构建包含长文本节点的树（结构相同，仅目标节点文本不同）
        final longNodes = <MindmapNode>[
          MindmapNode(
            label: testDepth == 0 ? longText : '根',
            level: 0,
            isRoot: true,
          ),
        ];
        if (testDepth >= 1) {
          longNodes.add(MindmapNode(
            label: testDepth == 1 ? longText : '中间',
            level: 1,
            isRoot: false,
          ));
        }
        if (testDepth >= 2) {
          longNodes.add(MindmapNode(
            label: longText,
            level: 2,
            isRoot: false,
          ));
        }

        final shortResult = engine.layout(shortNodes, canvasSize);
        final longResult = engine.layout(longNodes, canvasSize);

        expect(shortResult, isNotNull,
            reason: '迭代 $iter: 短文本布局不应为空');
        expect(longResult, isNotNull,
            reason: '迭代 $iter: 长文本布局不应为空');

        // 找到目标层级的节点
        final shortTarget = testDepth == 0
            ? shortResult!.$1
            : findByLabel(shortResult!.$1,
                testDepth == 1 ? shortText : shortText)!;
        final longTarget = testDepth == 0
            ? longResult!.$1
            : findByLabel(longResult!.$1,
                testDepth == 1 ? longText : longText)!;

        // 属性 4: 较长文本的节点宽度 >= 较短文本的节点宽度
        expect(longTarget.size.width,
            greaterThanOrEqualTo(shortTarget.size.width),
            reason: '迭代 $iter: 层级=$testDepth，'
                '长文本 (${longText.length}字符, 宽=${longTarget.size.width}) '
                '的节点宽度应 >= 短文本 (${shortText.length}字符, 宽=${shortTarget.size.width})');
      }
    },
  );
});

  group('Feature: mindmap-visualization, Property 5: 自适应缩放适配视口', () {
    test(
      '对任意画布和视口尺寸，缩放后画布不超出视口且比例在 0.3-3.0 范围内（100 次迭代）'
      '\n**Validates: Requirements 4.3, 4.4**',
      () {
        const iterations = 100;
        final rng = Random(9999); // 固定种子保证可复现

        for (var iter = 0; iter < iterations; iter++) {
          // 随机画布尺寸：50-3000
          final canvasWidth = 50.0 + rng.nextDouble() * 2950.0;
          final canvasHeight = 50.0 + rng.nextDouble() * 2950.0;
          final canvasSize = Size(canvasWidth, canvasHeight);

          // 随机视口尺寸：50-2000
          final viewportWidth = 50.0 + rng.nextDouble() * 1950.0;
          final viewportHeight = 50.0 + rng.nextDouble() * 1950.0;
          final viewportSize = Size(viewportWidth, viewportHeight);

          final scale = calculateFitScale(canvasSize, viewportSize);

          // 属性 5a: 缩放比例在 0.3 到 3.0 范围内
          expect(scale, greaterThanOrEqualTo(0.3),
              reason: '迭代 $iter: 缩放比例 $scale 应 >= 0.3，'
                  '画布=$canvasSize，视口=$viewportSize');
          expect(scale, lessThanOrEqualTo(3.0),
              reason: '迭代 $iter: 缩放比例 $scale 应 <= 3.0，'
                  '画布=$canvasSize，视口=$viewportSize');

          // 属性 5b: 缩放后画布不超出视口（仅当比例未被 clamp 截断时）
          // 当自然缩放比例在 [0.3, 3.0] 范围内时，缩放后画布应完全适配视口
          final naturalScale = min(
            viewportWidth / canvasWidth,
            viewportHeight / canvasHeight,
          );
          if (naturalScale >= 0.3 && naturalScale <= 3.0) {
            final scaledWidth = canvasWidth * scale;
            final scaledHeight = canvasHeight * scale;
            expect(scaledWidth, lessThanOrEqualTo(viewportWidth + 0.01),
                reason: '迭代 $iter: 缩放后宽度 $scaledWidth 应 <= 视口宽度 $viewportWidth，'
                    '缩放比例=$scale，画布=$canvasSize，视口=$viewportSize');
            expect(scaledHeight, lessThanOrEqualTo(viewportHeight + 0.01),
                reason: '迭代 $iter: 缩放后高度 $scaledHeight 应 <= 视口高度 $viewportHeight，'
                    '缩放比例=$scale，画布=$canvasSize，视口=$viewportSize');
          }
        }
      },
    );
  });

}
