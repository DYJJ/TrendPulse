/// 思维导图节点数据类
///
/// 表示 Mermaid mindmap 解析后的单个节点
class MindmapNode {
  /// 节点文本
  final String label;

  /// 缩进层级，0=根节点，1=观点，2=支持度
  final int level;

  /// 是否为根节点
  final bool isRoot;

  MindmapNode({
    required this.label,
    required this.level,
    required this.isRoot,
  });
}

/// 解析 Mermaid mindmap 格式代码为节点列表
///
/// 解析规则：
/// - 跳过第一行 "mindmap" 和空行
/// - 通过行首空格数计算缩进层级（每2个空格为一级）
/// - root((...)) 行提取根节点文本，层级为0
/// - 其他非空行作为子节点，层级由缩进决定
List<MindmapNode> parseMindmapCode(String code) {
  final lines = code.split('\n');
  final nodes = <MindmapNode>[];
  final rootPattern = RegExp(r'^\s*root\(\((.+?)\)\)\s*$');

  for (final line in lines) {
    if (line.trim().isEmpty || line.trim() == 'mindmap') continue;

    final rootMatch = rootPattern.firstMatch(line);
    if (rootMatch != null) {
      nodes.add(MindmapNode(
        label: rootMatch.group(1)!,
        level: 0,
        isRoot: true,
      ));
    } else {
      // 计算缩进层级：每2个空格为一级，减去 root 的基础缩进
      final indent = line.length - line.trimLeft().length;
      final level = (indent ~/ 2) - 1; // root 是 level 0（缩进2），子节点从 level 1 开始
      nodes.add(MindmapNode(
        label: line.trim(),
        level: level.clamp(1, 10),
        isRoot: false,
      ));
    }
  }
  return nodes;
}
