import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:trendpulse/providers/analysis_provider.dart';
import 'package:trendpulse/providers/posts_provider.dart';

/// 搜索页面 - Apple 风格大标题 + 搜索栏
class SearchPage extends StatefulWidget {
  /// 任务完成后的回调，用于通知父级切换 tab
  final VoidCallback? onTaskCompleted;

  const SearchPage({super.key, this.onTaskCompleted});

  @override
  State<SearchPage> createState() => _SearchPageState();
}

class _SearchPageState extends State<SearchPage> {
  final _keywordController = TextEditingController();
  final _limitController = TextEditingController(text: '1000');
  String _language = 'en';
  int _limit = 1000;
  final Set<String> _sources = {'reddit', 'youtube', 'twitter'};

  @override
  void dispose() {
    _keywordController.dispose();
    _limitController.dispose();
    super.dispose();
  }

  Future<void> _submit() async {
    final keyword = _keywordController.text.trim();
    if (keyword.isEmpty) return;

    final provider = context.read<AnalysisProvider>();
    await provider.createCollection(
      keyword: keyword,
      language: _language,
      limit: _limit,
      sources: _sources.toList(),
    );

    if (mounted) {
      if (provider.error != null) {
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: Text('错误: ${provider.error}'),
            behavior: SnackBarBehavior.floating,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
            backgroundColor: const Color(0xFFFF453A),
          ),
        );
      } else if (provider.taskId != null) {
        // 任务完成，主动触发帖子和导图加载
        final pp = context.read<PostsProvider>();
        pp.loadPosts(provider.taskId!);
        provider.loadMindmap(provider.taskId!);
        // 自动跳转到分析页
        widget.onTaskCompleted?.call();
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<AnalysisProvider>();

    return Scaffold(
      body: CustomScrollView(
        slivers: [
          // iOS 大标题
          const SliverToBoxAdapter(child: SizedBox(height: 60)),
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: Text('搜索', style: Theme.of(context).textTheme.displayLarge),
            ),
          ),
          const SliverToBoxAdapter(child: SizedBox(height: 12)),

          // 搜索栏
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: TextField(
                controller: _keywordController,
                style: const TextStyle(fontSize: 17),
                decoration: InputDecoration(
                  hintText: '输入话题关键词',
                  prefixIcon: Icon(Icons.search, color: const Color(0xFF8E8E93).withValues(alpha: 0.8)),
                ),
                onSubmitted: (_) => _submit(),
                onChanged: (_) => setState(() {}),
              ),
            ),
          ),
          const SliverToBoxAdapter(child: SizedBox(height: 28)),

          // 设置区域
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: _buildSettingsGroup(context),
            ),
          ),
          const SliverToBoxAdapter(child: SizedBox(height: 24)),

          // 数据源
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: _buildSourcesGroup(context),
            ),
          ),
          const SliverToBoxAdapter(child: SizedBox(height: 32)),

          // 按钮
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: SizedBox(
                height: 50,
                child: FilledButton(
                  onPressed: provider.isLoading || _keywordController.text.trim().isEmpty ? null : _submit,
                  style: FilledButton.styleFrom(
                    backgroundColor: const Color(0xFF0A84FF),
                    disabledBackgroundColor: const Color(0xFF0A84FF).withValues(alpha: 0.3),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(13)),
                  ),
                  child: provider.isLoading
                      ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white))
                      : const Text('开始分析', style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600)),
                ),
              ),
            ),
          ),

          // 任务状态
          if (provider.taskId != null)
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(20, 20, 20, 0),
                child: _TaskStatusTile(provider: provider),
              ),
            ),

          const SliverToBoxAdapter(child: SizedBox(height: 40)),
        ],
      ),
    );
  }

  /// iOS 分组列表风格的设置项
  Widget _buildSettingsGroup(BuildContext context) {
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF1C1C1E),
        borderRadius: BorderRadius.circular(13),
      ),
      child: Column(
        children: [
          // 语言
          _SettingsRow(
            label: '语言',
            trailing: SegmentedButton<String>(
              segments: const [
                ButtonSegment(value: 'en', label: Text('EN', style: TextStyle(fontSize: 13))),
                ButtonSegment(value: 'zh', label: Text('中文', style: TextStyle(fontSize: 13))),
              ],
              selected: {_language},
              onSelectionChanged: (v) => setState(() => _language = v.first),
              style: ButtonStyle(
                visualDensity: VisualDensity.compact,
                tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                side: WidgetStateProperty.all(const BorderSide(color: Color(0xFF48484A))),
              ),
            ),
          ),
          const Divider(height: 0.33, indent: 16, color: Color(0xFF38383A)),
          // 采集条数 - 输入框
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Text('采集条数', style: TextStyle(fontSize: 17)),
                    const Spacer(),
                    SizedBox(
                      width: 120,
                      height: 36,
                      child: TextField(
                        controller: _limitController,
                        keyboardType: TextInputType.number,
                        textAlign: TextAlign.center,
                        style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
                        decoration: InputDecoration(
                          contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
                          filled: true,
                          fillColor: const Color(0xFF2C2C2E),
                          border: OutlineInputBorder(
                            borderRadius: BorderRadius.circular(8),
                            borderSide: BorderSide.none,
                          ),
                        ),
                        onChanged: (v) {
                          final n = int.tryParse(v);
                          if (n != null && n >= 1 && n <= 500000) {
                            setState(() => _limit = n);
                          }
                        },
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                // 快捷预设按钮
                Wrap(
                  spacing: 8,
                  children: [
                    for (final preset in [
                      (100, '100'),
                      (1000, '1K'),
                      (10000, '10K'),
                      (50000, '50K'),
                      (100000, '100K'),
                      (500000, '500K'),
                    ])
                      _PresetChip(
                        label: preset.$2,
                        selected: _limit == preset.$1,
                        onTap: () => setState(() {
                          _limit = preset.$1;
                          _limitController.text = '${preset.$1}';
                        }),
                      ),
                  ],
                ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  /// 数据源选择 - iOS 分组列表
  Widget _buildSourcesGroup(BuildContext context) {
    const sourceData = [
      ('reddit', Icons.forum_rounded, Color(0xFFFF6723)),
      ('youtube', Icons.play_circle_rounded, Color(0xFFFF2D55)),
      ('twitter', Icons.tag_rounded, Color(0xFF0A84FF)),
    ];

    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF1C1C1E),
        borderRadius: BorderRadius.circular(13),
      ),
      child: Column(
        children: [
          for (var i = 0; i < sourceData.length; i++) ...[
            if (i > 0) const Divider(height: 0.33, indent: 52, color: Color(0xFF38383A)),
            _SourceRow(
              icon: sourceData[i].$2,
              color: sourceData[i].$3,
              label: sourceData[i].$1,
              selected: _sources.contains(sourceData[i].$1),
              onChanged: (v) {
                setState(() {
                  if (v) {
                    _sources.add(sourceData[i].$1);
                  } else if (_sources.length > 1) {
                    _sources.remove(sourceData[i].$1);
                  }
                });
              },
            ),
          ],
        ],
      ),
    );
  }
}

/// 设置行
class _SettingsRow extends StatelessWidget {
  final String label;
  final Widget trailing;

  const _SettingsRow({required this.label, required this.trailing});

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
      child: Row(
        children: [
          Text(label, style: const TextStyle(fontSize: 17)),
          const Spacer(),
          trailing,
        ],
      ),
    );
  }
}

/// 预设数量选择按钮
class _PresetChip extends StatelessWidget {
  final String label;
  final bool selected;
  final VoidCallback onTap;

  const _PresetChip({required this.label, required this.selected, required this.onTap});

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 6),
        decoration: BoxDecoration(
          color: selected ? const Color(0xFF0A84FF) : const Color(0xFF2C2C2E),
          borderRadius: BorderRadius.circular(8),
        ),
        child: Text(
          label,
          style: TextStyle(
            fontSize: 13,
            fontWeight: FontWeight.w600,
            color: selected ? Colors.white : const Color(0xFF8E8E93),
          ),
        ),
      ),
    );
  }
}

/// 数据源行 - 带开关
class _SourceRow extends StatelessWidget {
  final IconData icon;
  final Color color;
  final String label;
  final bool selected;
  final ValueChanged<bool> onChanged;

  const _SourceRow({
    required this.icon, required this.color, required this.label,
    required this.selected, required this.onChanged,
  });

  @override
  Widget build(BuildContext context) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 6),
      child: Row(
        children: [
          Container(
            width: 29, height: 29,
            decoration: BoxDecoration(color: color, borderRadius: BorderRadius.circular(7)),
            child: Icon(icon, size: 17, color: Colors.white),
          ),
          const SizedBox(width: 12),
          Text(label[0].toUpperCase() + label.substring(1), style: const TextStyle(fontSize: 17)),
          const Spacer(),
          Switch.adaptive(
            value: selected,
            onChanged: onChanged,
            activeTrackColor: const Color(0xFF30D158),
            activeThumbColor: Colors.white,
          ),
        ],
      ),
    );
  }
}

/// 任务状态
class _TaskStatusTile extends StatelessWidget {
  final AnalysisProvider provider;
  const _TaskStatusTile({required this.provider});

  @override
  Widget build(BuildContext context) {
    final done = provider.taskStatus == 'completed';
    final failed = provider.taskStatus == 'failed';
    final color = done ? const Color(0xFF30D158) : failed ? const Color(0xFFFF453A) : const Color(0xFF0A84FF);

    return Container(
      padding: const EdgeInsets.all(16),
      decoration: BoxDecoration(
        color: const Color(0xFF1C1C1E),
        borderRadius: BorderRadius.circular(13),
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(width: 8, height: 8, decoration: BoxDecoration(shape: BoxShape.circle, color: color)),
              const SizedBox(width: 8),
              Text(provider.taskStatus, style: TextStyle(fontSize: 15, fontWeight: FontWeight.w600, color: color)),
            ],
          ),
          if (!done && provider.progress > 0) ...[
            const SizedBox(height: 12),
            ClipRRect(
              borderRadius: BorderRadius.circular(2),
              child: LinearProgressIndicator(
                value: provider.progress / 100,
                minHeight: 3,
                backgroundColor: const Color(0xFF38383A),
                valueColor: AlwaysStoppedAnimation(color),
              ),
            ),
          ],
        ],
      ),
    );
  }
}
