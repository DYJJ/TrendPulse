import 'dart:math';
import 'package:flutter_test/flutter_test.dart';
import 'package:trendpulse/utils/mindmap_parser.dart';

/// 随机字符串生成器
///
/// 生成指定长度的随机中文/英文关键词
String _randomKeyword(Random rng) {
  // 使用常见中文字符和英文字母混合
  const chars = 'abcdefghijklmnopqrstuvwxyz人工智能科技数据分析舆情热点话题';
  final length = rng.nextInt(8) + 1;
  return String.fromCharCodes(
    List.generate(length, (_) => chars.codeUnitAt(rng.nextInt(chars.length))),
  );
}

/// 构造有效的 Mermaid mindmap 代码
///
/// 生成包含根节点和指定数量观点的 mindmap 代码字符串
String _buildMindmapCode(String rootLabel, List<String> opinions) {
  final buffer = StringBuffer();
  buffer.writeln('mindmap');
  buffer.writeln('  root(($rootLabel))');
  for (final opinion in opinions) {
    buffer.writeln('    $opinion');
  }
  return buffer.toString();
}

void main() {
  group('Property 1: Mindmap 解析结构不变量', () {
    /// **Validates: Requirements 2.1, 2.3**
    ///
    /// 对于任意有效的 Mermaid mindmap 代码字符串，解析后的节点列表应满足：
    /// - 第一个节点的 isRoot 为 true 且 level 为 0
    /// - 第一个节点的 label 等于 root((...)) 中括号内的文本
    /// - 所有非根节点的 isRoot 为 false 且 level >= 1
    /// - 节点总数等于原始代码中除 "mindmap" 行和空行之外的非空行数
    test('随机生成 mindmap 代码，验证解析结构不变量（100 次迭代）', () {
      final rng = Random(42); // 固定种子保证可复现

      for (var i = 0; i < 100; i++) {
        // 生成随机根节点关键词
        final rootLabel = _randomKeyword(rng);

        // 生成 1-20 个随机观点
        final opinionCount = rng.nextInt(20) + 1;
        final opinions = List.generate(opinionCount, (_) => _randomKeyword(rng));

        // 构造有效的 mindmap 代码
        final code = _buildMindmapCode(rootLabel, opinions);

        // 解析
        final nodes = parseMindmapCode(code);

        // 计算预期节点数：除 "mindmap" 行和空行之外的非空行数
        final expectedCount = code
            .split('\n')
            .where((line) => line.trim().isNotEmpty && line.trim() != 'mindmap')
            .length;

        // 不变量 1：第一个节点是根节点
        expect(nodes.first.isRoot, isTrue,
            reason: '迭代 $i: 第一个节点应为根节点');

        // 不变量 2：根节点 level 为 0
        expect(nodes.first.level, equals(0),
            reason: '迭代 $i: 根节点 level 应为 0');

        // 不变量 3：根节点 label 等于括号内文本
        expect(nodes.first.label, equals(rootLabel),
            reason: '迭代 $i: 根节点 label 应为 "$rootLabel"');

        // 不变量 4：所有非根节点 isRoot 为 false 且 level >= 1
        for (var j = 1; j < nodes.length; j++) {
          expect(nodes[j].isRoot, isFalse,
              reason: '迭代 $i: 节点 $j 不应为根节点');
          expect(nodes[j].level, greaterThanOrEqualTo(1),
              reason: '迭代 $i: 非根节点 $j 的 level 应 >= 1');
        }

        // 不变量 5：节点总数等于有效行数
        expect(nodes.length, equals(expectedCount),
            reason: '迭代 $i: 节点数应为 $expectedCount，实际为 ${nodes.length}');
      }
    });
  });

  group('Property 2: 支持度子节点层级正确性', () {
    /// **Validates: Requirements 2.3**
    ///
    /// 对于任意有效的 Mermaid mindmap 代码字符串，其中观点行缩进为 4 个空格（level 1），
    /// 支持度行缩进为 6 个空格（level 2），解析后支持度节点的 level 应严格大于
    /// 其前一个观点节点的 level。
    test('随机生成包含支持度的 mindmap 代码，验证支持度节点层级严格大于观点节点层级（100 次迭代）', () {
      final rng = Random(42);

      for (var i = 0; i < 100; i++) {
        final rootLabel = _randomKeyword(rng);

        // 生成 1-15 个观点，每个观点带一个支持度子节点
        final opinionCount = rng.nextInt(15) + 1;
        final buffer = StringBuffer();
        buffer.writeln('mindmap');
        buffer.writeln('  root(($rootLabel))');

        // 记录每个观点在节点列表中的预期索引（跳过根节点）
        final opinionIndices = <int>[];
        var nodeIndex = 1; // 根节点占索引 0

        for (var j = 0; j < opinionCount; j++) {
          final opinion = _randomKeyword(rng);
          final support = '${(rng.nextDouble() * 100).toStringAsFixed(1)}%';
          buffer.writeln('    $opinion'); // 4 空格缩进 = level 1
          opinionIndices.add(nodeIndex);
          nodeIndex++;
          buffer.writeln('      支持度: $support'); // 6 空格缩进 = level 2
          nodeIndex++;
        }

        final code = buffer.toString();
        final nodes = parseMindmapCode(code);

        // 验证每个支持度节点的 level 严格大于其前一个观点节点的 level
        for (final opIdx in opinionIndices) {
          final opinionNode = nodes[opIdx];
          final supportNode = nodes[opIdx + 1];

          expect(supportNode.level, greaterThan(opinionNode.level),
              reason: '迭代 $i: 支持度节点 level(${supportNode.level}) '
                  '应严格大于观点节点 level(${opinionNode.level})，'
                  '观点="${opinionNode.label}"，支持度="${supportNode.label}"');
        }
      }
    });
  });
}
