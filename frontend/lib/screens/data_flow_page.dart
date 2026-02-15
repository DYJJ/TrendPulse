import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:trendpulse/providers/analysis_provider.dart';
import 'package:trendpulse/providers/posts_provider.dart';
import 'package:trendpulse/widgets/post_item_widget.dart';

/// 数据流页面 - Apple 大标题 + 列表
class DataFlowPage extends StatefulWidget {
  const DataFlowPage({super.key});

  @override
  State<DataFlowPage> createState() => _DataFlowPageState();
}

class _DataFlowPageState extends State<DataFlowPage> {
  final _sc = ScrollController();

  /// 是否已自动重试过（防止无限重试）
  bool _hasAutoRetried = false;

  /// 搜索栏是否展开
  bool _searchExpanded = false;

  /// 搜索输入控制器
  final _searchController = TextEditingController();

  /// 是否显示回到顶部按钮
  bool _showScrollToTop = false;

  @override
  void initState() {
    super.initState();
    _sc.addListener(_onScroll);
    WidgetsBinding.instance.addPostFrameCallback((_) => _tryLoad());
  }

  @override
  void dispose() {
    _sc.dispose();
    _searchController.dispose();
    super.dispose();
  }

  void _tryLoad() {
    final ap = context.read<AnalysisProvider>();
    final pp = context.read<PostsProvider>();
    // 只要 taskId 存在且任务已完成（不在采集中）就加载帖子
    if (ap.taskId != null && !ap.isLoading && pp.taskId != ap.taskId) {
      _hasAutoRetried = false;
      pp.loadPosts(ap.taskId!);
    }
  }

  void _onScroll() {
    // 无限滚动加载
    if (_sc.position.pixels >= _sc.position.maxScrollExtent - 200) {
      context.read<PostsProvider>().loadMore();
    }
    // 回到顶部按钮：超过一屏距离时显示
    final shouldShow = _sc.position.pixels > _sc.position.viewportDimension;
    if (shouldShow != _showScrollToTop) {
      setState(() => _showScrollToTop = shouldShow);
    }
  }

  /// 平滑滚动到顶部
  void _scrollToTop() {
    _sc.animateTo(0, duration: const Duration(milliseconds: 400), curve: Curves.easeOutCubic);
  }

  @override
  Widget build(BuildContext context) {
    final ap = context.watch<AnalysisProvider>();
    final pp = context.watch<PostsProvider>();

    // taskId 存在且任务已完成时自动加载帖子列表
    if (ap.taskId != null && !ap.isLoading && pp.taskId != ap.taskId) {
      WidgetsBinding.instance.addPostFrameCallback((_) => pp.loadPosts(ap.taskId!));
    }
    // 加载失败时自动重试一次（处理竞态条件）
    else if (ap.taskId != null && !ap.isLoading && pp.error != null && pp.posts.isEmpty && !pp.isLoading && !_hasAutoRetried) {
      _hasAutoRetried = true;
      WidgetsBinding.instance.addPostFrameCallback((_) => pp.loadPosts(ap.taskId!));
    }
    // 加载失败时自动重试一次（处理竞态条件）
    else if (ap.taskId != null && pp.error != null && pp.posts.isEmpty && !pp.isLoading && !_hasAutoRetried) {
      _hasAutoRetried = true;
      WidgetsBinding.instance.addPostFrameCallback((_) => pp.loadPosts(ap.taskId!));
    }

    return Scaffold(
      // 回到顶部浮动按钮
      floatingActionButton: _showScrollToTop && pp.taskId != null
          ? FloatingActionButton.small(
              onPressed: _scrollToTop,
              backgroundColor: const Color(0xFF2C2C2E),
              child: const Icon(Icons.arrow_upward_rounded, color: Color(0xFF8E8E93)),
            )
          : null,
      body: pp.taskId == null
          ? _empty(context)
          : RefreshIndicator(
              onRefresh: () => pp.refresh(),
              child: CustomScrollView(
              controller: _sc,
              slivers: [
                const SliverToBoxAdapter(child: SizedBox(height: 60)),
                SliverToBoxAdapter(
                  child: Padding(
                    padding: const EdgeInsets.symmetric(horizontal: 20),
                    child: Row(
                      children: [
                        Text('数据', style: Theme.of(context).textTheme.displayLarge),
                        const Spacer(),
                        if (pp.total > 0)
                          Text('${pp.total} 条', style: const TextStyle(fontSize: 15, color: Color(0xFF8E8E93))),
                      ],
                    ),
                  ),
                ),
                const SliverToBoxAdapter(child: SizedBox(height: 8)),
                // 可展开搜索栏
                SliverToBoxAdapter(child: _buildSearchBar(pp)),
                // 平台筛选芯片 + 排序按钮
                SliverToBoxAdapter(child: _buildFilterRow(pp)),
                const SliverToBoxAdapter(child: SizedBox(height: 12)),
                // 平台统计摘要
                if (pp.posts.isNotEmpty)
                  SliverToBoxAdapter(child: _buildPlatformStats(pp)),
                // 列表
                if (pp.isLoading && pp.posts.isEmpty)
                  const SliverFillRemaining(child: Center(child: CircularProgressIndicator.adaptive()))
                else if (pp.error != null && pp.posts.isEmpty)
                  SliverFillRemaining(
                    child: Center(
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Text(pp.error!, style: const TextStyle(color: Color(0xFF8E8E93), fontSize: 15)),
                          const SizedBox(height: 16),
                          TextButton(
                            onPressed: () => pp.loadPosts(ap.taskId!),
                            child: const Text('重试'),
                          ),
                        ],
                      ),
                    ),
                  )
                else if (pp.posts.isEmpty && _hasActiveFilters(pp))
                  SliverFillRemaining(child: _buildFilteredEmptyState(pp))
                else if (pp.posts.isEmpty)
                  const SliverFillRemaining(child: Center(child: Text('暂无数据', style: TextStyle(color: Color(0xFF8E8E93)))))
                else
                  SliverToBoxAdapter(
                    child: Container(
                      margin: const EdgeInsets.symmetric(horizontal: 20),
                      decoration: BoxDecoration(
                        color: const Color(0xFF1C1C1E),
                        borderRadius: BorderRadius.circular(13),
                      ),
                      child: Column(
                        children: [
                          for (var i = 0; i < pp.posts.length; i++) ...[
                            if (i > 0) const Divider(height: 0.33, indent: 64, color: Color(0xFF38383A)),
                            PostItemWidget(post: pp.posts[i]),
                          ],
                          if (pp.hasMore)
                            _buildLoadingPlaceholder(pp),
                        ],
                      ),
                    ),
                  ),
                const SliverToBoxAdapter(child: SizedBox(height: 40)),
              ],
            ),
          ),
    );
  }

  /// 构建可展开搜索栏
  Widget _buildSearchBar(PostsProvider pp) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20),
      child: Row(
        children: [
          // 搜索图标按钮
          GestureDetector(
            onTap: () {
              setState(() {
                _searchExpanded = !_searchExpanded;
                if (!_searchExpanded) {
                  _searchController.clear();
                  pp.setSearch(null);
                }
              });
            },
            child: Icon(
              _searchExpanded ? Icons.close_rounded : Icons.search_rounded,
              color: const Color(0xFF8E8E93),
              size: 22,
            ),
          ),
          // 展开的搜索输入框
          if (_searchExpanded) ...[
            const SizedBox(width: 8),
            Expanded(
              child: SizedBox(
                height: 36,
                child: TextField(
                  controller: _searchController,
                  style: const TextStyle(fontSize: 15),
                  decoration: InputDecoration(
                    hintText: '搜索帖子...',
                    hintStyle: const TextStyle(fontSize: 15, color: Color(0xFF636366)),
                    contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 0),
                    filled: true,
                    fillColor: const Color(0xFF2C2C2E),
                    border: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(10),
                      borderSide: BorderSide.none,
                    ),
                    suffixIcon: _searchController.text.isNotEmpty
                        ? GestureDetector(
                            onTap: () {
                              _searchController.clear();
                              pp.setSearch(null);
                            },
                            child: const Icon(Icons.clear_rounded, size: 18, color: Color(0xFF8E8E93)),
                          )
                        : null,
                  ),
                  textInputAction: TextInputAction.search,
                  onSubmitted: (value) => pp.setSearch(value),
                  onChanged: (_) => setState(() {}),
                ),
              ),
            ),
          ],
        ],
      ),
    );
  }

  /// 构建平台筛选芯片行 + 排序按钮
  Widget _buildFilterRow(PostsProvider pp) {
    // 平台筛选选项
    const platforms = <String?>[null, 'reddit', 'youtube', 'twitter'];
    const labels = ['全部', 'Reddit', 'YouTube', 'Twitter'];
    const colors = [
      Color(0xFF8E8E93), // 全部
      Color(0xFFFF6723), // Reddit
      Color(0xFFFF2D55), // YouTube
      Color(0xFF0A84FF), // Twitter
    ];

    // 排序选项标签
    String sortLabel() {
      switch (pp.sortBy) {
        case 'likes': return '最多点赞';
        case 'comments': return '最多评论';
        default: return '最新优先';
      }
    }

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20),
      child: Row(
        children: [
          // 平台筛选芯片组
          Expanded(
            child: SingleChildScrollView(
              scrollDirection: Axis.horizontal,
              child: Row(
                children: List.generate(platforms.length, (i) {
                  final selected = pp.sourceFilter == platforms[i];
                  final chipColor = colors[i];
                  return Padding(
                    padding: EdgeInsets.only(right: i < platforms.length - 1 ? 8 : 0),
                    child: ChoiceChip(
                      label: Text(labels[i]),
                      selected: selected,
                      onSelected: (_) => pp.setSourceFilter(platforms[i]),
                      selectedColor: chipColor.withValues(alpha: 0.2),
                      backgroundColor: const Color(0xFF2C2C2E),
                      labelStyle: TextStyle(
                        fontSize: 13,
                        fontWeight: FontWeight.w500,
                        color: selected ? chipColor : const Color(0xFF8E8E93),
                      ),
                      side: BorderSide(
                        color: selected ? chipColor.withValues(alpha: 0.4) : Colors.transparent,
                      ),
                      shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(18)),
                      showCheckmark: false,
                      materialTapTargetSize: MaterialTapTargetSize.shrinkWrap,
                      visualDensity: VisualDensity.compact,
                    ),
                  );
                }),
              ),
            ),
          ),
          const SizedBox(width: 8),
          // 排序按钮
          PopupMenuButton<String>(
            onSelected: (value) => pp.setSortBy(value),
            itemBuilder: (_) => const [
              PopupMenuItem(value: 'timestamp', child: Text('最新优先')),
              PopupMenuItem(value: 'likes', child: Text('最多点赞')),
              PopupMenuItem(value: 'comments', child: Text('最多评论')),
            ],
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
              decoration: BoxDecoration(
                color: const Color(0xFF2C2C2E),
                borderRadius: BorderRadius.circular(18),
              ),
              child: Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.sort_rounded, size: 16, color: Color(0xFF8E8E93)),
                  const SizedBox(width: 4),
                  Text(sortLabel(), style: const TextStyle(fontSize: 13, color: Color(0xFF8E8E93))),
                ],
              ),
            ),
          ),
        ],
      ),
    );
  }

  /// 判断是否有激活的筛选/搜索条件
  bool _hasActiveFilters(PostsProvider pp) {
    return pp.sourceFilter != null || pp.searchQuery != null;
  }

  /// 构建平台统计摘要
  Widget _buildPlatformStats(PostsProvider pp) {
    // 从当前已加载的帖子中统计各平台数量
    final counts = <String, int>{};
    for (final post in pp.posts) {
      counts[post.source] = (counts[post.source] ?? 0) + 1;
    }

    const platformColors = {
      'reddit': Color(0xFFFF6723),
      'youtube': Color(0xFFFF2D55),
      'twitter': Color(0xFF0A84FF),
    };

    const platformLabels = {
      'reddit': 'Reddit',
      'youtube': 'YouTube',
      'twitter': 'Twitter',
    };

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 4),
      child: Row(
        children: counts.entries.map((entry) {
          final color = platformColors[entry.key] ?? const Color(0xFF8E8E93);
          final label = platformLabels[entry.key] ?? entry.key;
          return Padding(
            padding: const EdgeInsets.only(right: 12),
            child: Row(
              mainAxisSize: MainAxisSize.min,
              children: [
                Container(
                  width: 8,
                  height: 8,
                  decoration: BoxDecoration(color: color, shape: BoxShape.circle),
                ),
                const SizedBox(width: 4),
                Text(
                  '$label ${entry.value}',
                  style: TextStyle(fontSize: 12, color: color, fontWeight: FontWeight.w500),
                ),
              ],
            ),
          );
        }).toList(),
      ),
    );
  }

  /// 构建筛选条件下的空状态提示
  Widget _buildFilteredEmptyState(PostsProvider pp) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.filter_list_off_rounded, size: 48, color: const Color(0xFF8E8E93).withValues(alpha: 0.4)),
          const SizedBox(height: 16),
          const Text(
            '没有匹配的结果',
            style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600, color: Color(0xFF8E8E93)),
          ),
          const SizedBox(height: 6),
          Text(
            pp.searchQuery != null ? '尝试更换搜索关键词' : '尝试切换平台筛选条件',
            style: const TextStyle(fontSize: 14, color: Color(0xFF636366)),
          ),
          const SizedBox(height: 20),
          TextButton.icon(
            onPressed: () {
              if (pp.searchQuery != null) {
                _searchController.clear();
                pp.setSearch(null);
              }
              if (pp.sourceFilter != null) {
                pp.setSourceFilter(null);
              }
            },
            icon: const Icon(Icons.clear_all_rounded, size: 18),
            label: const Text('清除所有筛选'),
          ),
        ],
      ),
    );
  }

  /// 构建底部加载占位符（骨架屏或重试按钮）
  Widget _buildLoadingPlaceholder(PostsProvider pp) {
    // 加载失败时展示重试按钮和错误提示
    if (pp.error != null) {
      return Padding(
        padding: const EdgeInsets.all(16),
        child: Column(
          children: [
            const Text(
              '加载失败',
              style: TextStyle(fontSize: 14, color: Color(0xFF8E8E93)),
            ),
            const SizedBox(height: 8),
            TextButton.icon(
              onPressed: () => pp.loadMore(),
              icon: const Icon(Icons.refresh_rounded, size: 16),
              label: const Text('重试'),
            ),
          ],
        ),
      );
    }
    // 正常加载中展示骨架屏
    return const ShimmerLoadingPlaceholder();
  }

  Widget _empty(BuildContext context) {
    return Center(
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(Icons.list_rounded, size: 56, color: const Color(0xFF8E8E93).withValues(alpha: 0.3)),
          const SizedBox(height: 16),
          const Text('暂无数据', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w600, color: Color(0xFF8E8E93))),
          const SizedBox(height: 6),
          const Text('在搜索页面发起采集任务', style: TextStyle(fontSize: 15, color: Color(0xFF636366))),
        ],
      ),
    );
  }
}


/// 骨架屏加载占位符组件
///
/// 使用渐变动画模拟内容加载中的闪烁效果，替代简单的加载圈。
class ShimmerLoadingPlaceholder extends StatefulWidget {
  const ShimmerLoadingPlaceholder({super.key});

  @override
  State<ShimmerLoadingPlaceholder> createState() => _ShimmerLoadingPlaceholderState();
}

class _ShimmerLoadingPlaceholderState extends State<ShimmerLoadingPlaceholder>
    with SingleTickerProviderStateMixin {
  late final AnimationController _controller;

  @override
  void initState() {
    super.initState();
    _controller = AnimationController(
      vsync: this,
      duration: const Duration(milliseconds: 1200),
    )..repeat();
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return AnimatedBuilder(
      animation: _controller,
      builder: (context, child) {
        return Padding(
          padding: const EdgeInsets.symmetric(vertical: 12, horizontal: 16),
          child: Column(
            children: List.generate(2, (index) {
              return Padding(
                padding: EdgeInsets.only(bottom: index < 1 ? 12 : 0),
                child: Row(
                  children: [
                    // 头像占位
                    _shimmerBox(width: 40, height: 40, circular: true),
                    const SizedBox(width: 12),
                    Expanded(
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          // 标题占位
                          _shimmerBox(width: double.infinity, height: 14),
                          const SizedBox(height: 8),
                          // 副标题占位
                          _shimmerBox(width: 160, height: 10),
                        ],
                      ),
                    ),
                  ],
                ),
              );
            }),
          ),
        );
      },
    );
  }

  /// 构建单个闪烁占位块
  Widget _shimmerBox({required double height, double? width, bool circular = false}) {
    final shimmerValue = _controller.value;
    // 渐变高亮位置随动画移动
    final highlightPosition = shimmerValue * 2 - 0.5;
    return Container(
      width: width,
      height: height,
      decoration: BoxDecoration(
        borderRadius: circular ? null : BorderRadius.circular(4),
        shape: circular ? BoxShape.circle : BoxShape.rectangle,
        gradient: LinearGradient(
          begin: Alignment.centerLeft,
          end: Alignment.centerRight,
          colors: const [
            Color(0xFF2C2C2E),
            Color(0xFF3A3A3C),
            Color(0xFF2C2C2E),
          ],
          stops: [
            (highlightPosition - 0.3).clamp(0.0, 1.0),
            highlightPosition.clamp(0.0, 1.0),
            (highlightPosition + 0.3).clamp(0.0, 1.0),
          ],
        ),
      ),
    );
  }
}
