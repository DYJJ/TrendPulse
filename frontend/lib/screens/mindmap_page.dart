import 'package:flutter/gestures.dart';
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:provider/provider.dart';
import 'package:trendpulse/providers/analysis_provider.dart';
import 'package:trendpulse/utils/mindmap_layout.dart';
import 'package:trendpulse/utils/mindmap_parser.dart';
import 'package:trendpulse/widgets/mindmap_painter.dart';

/// 思维导图页面 - 图形化渲染版本
///
/// 使用 CustomPainter + InteractiveViewer 实现图形化思维导图，
/// 支持鼠标拖动、滚轮缩放、悬浮高亮和点击反馈。
class MindMapPage extends StatefulWidget {
  const MindMapPage({super.key});

  @override
  State<MindMapPage> createState() => _MindMapPageState();
}

class _MindMapPageState extends State<MindMapPage> {
  /// 记录已尝试加载的 taskId，避免重复触发
  String? _loadedTaskId;

  /// 是否已自动重试过（防止无限重试）
  bool _hasAutoRetried = false;

  /// 布局引擎实例
  final MindmapLayoutEngine _layoutEngine = MindmapLayoutEngine();

  /// 是否已完成首次自适应缩放
  bool _hasAutoFitted = false;

  /// 缓存的 mermaidCode，用于检测数据变化
  String? _cachedCode;

  /// 当前鼠标悬浮的节点
  LayoutNode? _hoveredNode;

  /// 缓存的布局根节点，用于命中测试
  LayoutNode? _layoutRoot;

  /// 当前缩放比例
  double _scale = 1.0;

  /// 当前平移偏移量（屏幕坐标系）
  Offset _offset = Offset.zero;

  /// 缓存的画布尺寸
  Size _canvasSize = Size.zero;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      _tryLoadMindmap();
    });
  }

  @override
  void dispose() {
    super.dispose();
  }

  /// 尝试加载思维导图数据
  void _tryLoadMindmap() {
    final p = context.read<AnalysisProvider>();
    // 只有任务已完成（不在采集中）且导图未加载时才触发
    if (p.taskId != null && !p.isLoading && p.mermaidCode == null && !p.isMindmapLoading && _loadedTaskId != p.taskId) {
      _loadedTaskId = p.taskId;
      _hasAutoRetried = false;
      p.loadMindmap(p.taskId!);
    }
  }

  /// 显示 Mermaid 源代码底部弹出面板
  void _showCodeSheet(BuildContext context, String code) {
    showModalBottomSheet(
      context: context,
      backgroundColor: const Color(0xFF1C1C1E),
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
      ),
      isScrollControlled: true,
      builder: (ctx) => DraggableScrollableSheet(
        initialChildSize: 0.6,
        minChildSize: 0.3,
        maxChildSize: 0.9,
        expand: false,
        builder: (ctx, scrollController) => Column(
          children: [
            // 拖拽指示条
            Padding(
              padding: const EdgeInsets.only(top: 10, bottom: 8),
              child: Container(
                width: 36,
                height: 4,
                decoration: BoxDecoration(
                  color: const Color(0xFF48484A),
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
            // 标题栏 + 复制按钮
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 8),
              child: Row(
                children: [
                  const Text(
                    'Mermaid 源代码',
                    style: TextStyle(
                      fontSize: 17,
                      fontWeight: FontWeight.w600,
                      color: Colors.white,
                    ),
                  ),
                  const Spacer(),
                  GestureDetector(
                    onTap: () {
                      Clipboard.setData(ClipboardData(text: code));
                      Navigator.pop(ctx);
                      ScaffoldMessenger.of(context).showSnackBar(
                        SnackBar(
                          content: const Text('已拷贝'),
                          behavior: SnackBarBehavior.floating,
                          backgroundColor: const Color(0xFF30D158),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(10),
                          ),
                        ),
                      );
                    },
                    child: Container(
                      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
                      decoration: BoxDecoration(
                        color: const Color(0xFF0A84FF),
                        borderRadius: BorderRadius.circular(16),
                      ),
                      child: const Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(Icons.copy_rounded, size: 14, color: Colors.white),
                          SizedBox(width: 4),
                          Text('复制', style: TextStyle(fontSize: 14, color: Colors.white, fontWeight: FontWeight.w500)),
                        ],
                      ),
                    ),
                  ),
                ],
              ),
            ),
            const Divider(height: 1, color: Color(0xFF38383A)),
            // 源代码内容
            Expanded(
              child: SingleChildScrollView(
                controller: scrollController,
                padding: const EdgeInsets.all(16),
                child: SelectableText(
                  code,
                  style: const TextStyle(
                    fontFamily: 'SF Mono, monospace',
                    fontSize: 13,
                    color: Color(0xFFEBEBF5),
                    height: 1.6,
                  ),
                ),
              ),
            ),
          ],
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final p = context.watch<AnalysisProvider>();
    final code = p.mermaidCode;

    // taskId 变化且任务已完成时自动触发加载
    if (p.taskId != null && !p.isLoading && code == null && !p.isMindmapLoading && _loadedTaskId != p.taskId) {
      WidgetsBinding.instance.addPostFrameCallback((_) => _tryLoadMindmap());
    }

    // 错误状态：任务已完成后自动重试一次（处理竞态条件）
    if (p.error != null && code == null && !p.isMindmapLoading && !p.isLoading && !_hasAutoRetried) {
      _hasAutoRetried = true;
      WidgetsBinding.instance.addPostFrameCallback((_) {
        if (p.taskId != null) p.loadMindmap(p.taskId!);
      });
    }

    // 数据变化时重置自适应缩放标记
    if (code != _cachedCode) {
      _cachedCode = code;
      _hasAutoFitted = false;
    }

    if (p.taskId == null) return _empty(context);
    if (p.isMindmapLoading) {
      return const Center(child: CircularProgressIndicator.adaptive());
    }

    // 错误状态：显示错误信息和重试按钮
    if (p.error != null && code == null) {
      return Center(
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            Icon(Icons.error_outline_rounded, size: 56, color: const Color(0xFF8E8E93).withValues(alpha: 0.3)),
            const SizedBox(height: 16),
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 32),
              child: Text(
                p.error!,
                textAlign: TextAlign.center,
                style: const TextStyle(fontSize: 15, color: Color(0xFF8E8E93)),
              ),
            ),
            const SizedBox(height: 20),
            GestureDetector(
              onTap: () => p.loadMindmap(p.taskId!),
              child: Container(
                padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 10),
                decoration: BoxDecoration(
                  color: const Color(0xFF0A84FF),
                  borderRadius: BorderRadius.circular(20),
                ),
                child: const Text('重试', style: TextStyle(fontSize: 15, color: Colors.white, fontWeight: FontWeight.w500)),
              ),
            ),
          ],
        ),
      );
    }

    // 数据尚未加载完成时显示空状态
    if (code == null) return _empty(context);

    return Scaffold(
      body: Column(
        children: [
          const SizedBox(height: 60),
          // 标题栏
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20),
            child: Row(
              children: [
                Text('导图', style: Theme.of(context).textTheme.displayLarge),
                const Spacer(),
                GestureDetector(
                  onTap: () => _showCodeSheet(context, code),
                  child: const Text('查看代码', style: TextStyle(fontSize: 17, color: Color(0xFF0A84FF))),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),
          // 图形化思维导图区域
          Expanded(
            child: _buildMindmapCanvas(context, code),
          ),
        ],
      ),
    );
  }

  /// 构建图形化思维导图画布
  ///
  /// 使用固定视口大小的 CustomPaint，通过 _offset 和 _scale
  /// 在 paint 方法外部用 Transform 控制视图变换。
  /// 手势直接操作 _offset 和 _scale，避免矩阵计算错误。
  Widget _buildMindmapCanvas(BuildContext context, String code) {
    final nodes = parseMindmapCode(code);
    if (nodes.isEmpty) return _empty(context);

    return LayoutBuilder(
      builder: (context, constraints) {
        final viewportSize = Size(constraints.maxWidth, constraints.maxHeight);
        // 画布尺寸：使用视口的 3 倍以留出足够空间
        _canvasSize = Size(viewportSize.width * 3, viewportSize.height * 3);

        final result = _layoutEngine.layout(nodes, _canvasSize);
        if (result == null) return _empty(context);

        final (root, layoutCanvasSize) = result;
        _layoutRoot = root;
        _canvasSize = layoutCanvasSize;

        // 首次加载时自动适配缩放并居中
        if (!_hasAutoFitted) {
          _hasAutoFitted = true;
          WidgetsBinding.instance.addPostFrameCallback((_) {
            _applyFitScale(layoutCanvasSize, viewportSize);
          });
        }

        return MouseRegion(
          cursor: _hoveredNode != null
              ? SystemMouseCursors.click
              : SystemMouseCursors.grab,
          onHover: _handleHover,
          onExit: (_) {
            if (_hoveredNode != null) {
              setState(() => _hoveredNode = null);
            }
          },
          child: Listener(
            onPointerSignal: (event) {
              if (event is PointerScrollEvent) {
                _handleScrollZoom(event);
              }
            },
            child: GestureDetector(
              behavior: HitTestBehavior.opaque,
              onPanUpdate: _handlePanUpdate,
              onTapUp: _handleTap,
              child: ClipRect(
                child: CustomPaint(
                  painter: TransformedMindmapPainter(
                    root: root,
                    hoveredNode: _hoveredNode,
                    scale: _scale,
                    offset: _offset,
                  ),
                  size: viewportSize,
                ),
              ),
            ),
          ),
        );
      },
    );
  }

  /// 将屏幕坐标转换为画布坐标
  Offset _screenToCanvas(Offset screenPos) {
    return (screenPos - _offset) / _scale;
  }

  /// 在布局树中查找包含指定坐标的节点
  LayoutNode? _hitTestNode(Offset canvasPos, LayoutNode node) {
    for (final child in node.children) {
      final hit = _hitTestNode(canvasPos, child);
      if (hit != null) return hit;
    }
    final rect = Rect.fromCenter(
      center: node.position,
      width: node.size.width + 8,
      height: node.size.height + 8,
    );
    if (rect.contains(canvasPos)) return node;
    return null;
  }

  /// 处理鼠标悬浮事件
  void _handleHover(PointerHoverEvent event) {
    if (_layoutRoot == null) return;
    final canvasPos = _screenToCanvas(event.localPosition);
    final hit = _hitTestNode(canvasPos, _layoutRoot!);
    if (hit != _hoveredNode) {
      setState(() => _hoveredNode = hit);
    }
  }

  /// 处理拖动平移（屏幕坐标系直接偏移）
  void _handlePanUpdate(DragUpdateDetails details) {
    setState(() {
      _offset += details.delta;
    });
  }

  /// 处理鼠标滚轮缩放（以鼠标位置为中心）
  void _handleScrollZoom(PointerScrollEvent event) {
    final delta = event.scrollDelta.dy;
    final scaleFactor = delta > 0 ? 0.92 : 1.08;
    final newScale = (_scale * scaleFactor).clamp(0.3, 3.0);
    if ((newScale - _scale).abs() < 0.001) return;

    // 以鼠标位置为缩放中心：
    // 缩放前鼠标指向的画布坐标 = (mousePos - offset) / oldScale
    // 缩放后要保持这个画布坐标不变：mousePos = canvasPos * newScale + newOffset
    // 所以 newOffset = mousePos - canvasPos * newScale
    final mousePos = event.localPosition;
    final canvasPos = (mousePos - _offset) / _scale;

    setState(() {
      _offset = mousePos - canvasPos * newScale;
      _scale = newScale;
    });
  }

  /// 处理点击事件
  void _handleTap(TapUpDetails details) {
    if (_layoutRoot == null) return;
    final canvasPos = _screenToCanvas(details.localPosition);
    final hit = _hitTestNode(canvasPos, _layoutRoot!);
    if (hit == null) return;

    HapticFeedback.lightImpact();
    final label = hit.data.label;
    Clipboard.setData(ClipboardData(text: label));
    ScaffoldMessenger.of(context).clearSnackBars();
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text('已复制: $label', maxLines: 1, overflow: TextOverflow.ellipsis),
        behavior: SnackBarBehavior.floating,
        backgroundColor: const Color(0xFF30D158),
        duration: const Duration(seconds: 1),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
      ),
    );
  }

  /// 应用自适应缩放，使导图适配视口并居中
  void _applyFitScale(Size canvasSize, Size viewportSize) {
    final scale = calculateFitScale(canvasSize, viewportSize);

    // 计算平移偏移量，使画布居中于视口
    final scaledWidth = canvasSize.width * scale;
    final scaledHeight = canvasSize.height * scale;
    final tx = (viewportSize.width - scaledWidth) / 2;
    final ty = (viewportSize.height - scaledHeight) / 2;

    setState(() {
      _scale = scale;
      _offset = Offset(tx, ty);
    });
  }

  Widget _empty(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.account_tree_rounded, size: 56, color: const Color(0xFF8E8E93).withValues(alpha: 0.3)),
          const SizedBox(height: 16),
          const Text('暂无导图', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600, color: Color(0xFF8E8E93))),
          const SizedBox(height: 6),
          const Text('在搜索页面发起采集任务', style: TextStyle(fontSize: 15, color: Color(0xFF636366))),
        ],
      ),
    );
  }
}
