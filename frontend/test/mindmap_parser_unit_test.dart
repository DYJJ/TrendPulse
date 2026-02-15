import 'package:flutter_test/flutter_test.dart';
import 'package:trendpulse/utils/mindmap_parser.dart';

void main() {
  group('parseMindmapCode 边界情况单元测试', () {
    test('空字符串返回空列表', () {
      final nodes = parseMindmapCode('');
      expect(nodes, isEmpty);
    });

    test('仅含 "mindmap" 的代码返回空列表', () {
      final nodes = parseMindmapCode('mindmap');
      expect(nodes, isEmpty);
    });

    test('仅含 "mindmap" 和空行的代码返回空列表', () {
      final nodes = parseMindmapCode('mindmap\n\n\n');
      expect(nodes, isEmpty);
    });

    test('标准后端输出格式解析正确', () {
      const code = '''mindmap
  root((人工智能))
    支持AI发展
      支持度: 45.0%
    反对AI滥用
      支持度: 30.0%
    保持中立观望
      支持度: 25.0%''';

      final nodes = parseMindmapCode(code);

      // 共 7 个节点：1 根 + 3 观点 + 3 支持度
      expect(nodes.length, equals(7));

      // 根节点
      expect(nodes[0].isRoot, isTrue);
      expect(nodes[0].label, equals('人工智能'));
      expect(nodes[0].level, equals(0));

      // 第一个观点
      expect(nodes[1].label, equals('支持AI发展'));
      expect(nodes[1].level, equals(1));
      expect(nodes[1].isRoot, isFalse);

      // 第一个支持度
      expect(nodes[2].label, equals('支持度: 45.0%'));
      expect(nodes[2].level, equals(2));

      // 第二个观点
      expect(nodes[3].label, equals('反对AI滥用'));
      expect(nodes[3].level, equals(1));

      // 第二个支持度
      expect(nodes[4].label, equals('支持度: 30.0%'));
      expect(nodes[4].level, equals(2));
    });

    test('包含全角特殊字符的代码解析正确', () {
      const code = '''mindmap
  root((【舆情分析】))
    「正面观点」——支持
      支持度：80.0％
    （负面观点）——反对
      支持度：20.0％''';

      final nodes = parseMindmapCode(code);

      expect(nodes.length, equals(5));
      expect(nodes[0].isRoot, isTrue);
      expect(nodes[0].label, equals('【舆情分析】'));
      expect(nodes[1].label, equals('「正面观点」——支持'));
      expect(nodes[2].label, equals('支持度：80.0％'));
      expect(nodes[3].label, equals('（负面观点）——反对'));
      expect(nodes[4].label, equals('支持度：20.0％'));
    });
  });
}
