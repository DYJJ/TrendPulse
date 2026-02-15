import 'package:flutter/material.dart';
import 'package:provider/provider.dart';
import 'package:trendpulse/providers/subscription_provider.dart';

/// 订阅管理页面 — 创建关键词订阅、查看订阅列表、取消订阅
class SubscriptionPage extends StatefulWidget {
  const SubscriptionPage({super.key});

  @override
  State<SubscriptionPage> createState() => _SubscriptionPageState();
}

class _SubscriptionPageState extends State<SubscriptionPage> {
  final _keywordController = TextEditingController();
  int _intervalHours = 6;
  int _alertThreshold = 30;

  @override
  void initState() {
    super.initState();
    // 页面加载时拉取订阅列表
    Future.microtask(() {
      context.read<SubscriptionProvider>().loadSubscriptions();
    });
  }

  @override
  void dispose() {
    _keywordController.dispose();
    super.dispose();
  }

  Future<void> _createSubscription() async {
    final keyword = _keywordController.text.trim();
    if (keyword.isEmpty) return;

    final provider = context.read<SubscriptionProvider>();
    await provider.createSubscription(
      keyword: keyword,
      intervalHours: _intervalHours,
      alertThreshold: _alertThreshold,
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
      } else {
        _keywordController.clear();
        ScaffoldMessenger.of(context).showSnackBar(
          SnackBar(
            content: const Text('订阅创建成功'),
            behavior: SnackBarBehavior.floating,
            shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
            backgroundColor: const Color(0xFF30D158),
          ),
        );
      }
    }
  }

  @override
  Widget build(BuildContext context) {
    final provider = context.watch<SubscriptionProvider>();

    return Scaffold(
      body: CustomScrollView(
        slivers: [
          const SliverToBoxAdapter(child: SizedBox(height: 60)),
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: Text('订阅', style: Theme.of(context).textTheme.displayLarge),
            ),
          ),
          const SliverToBoxAdapter(child: SizedBox(height: 12)),

          // 新建订阅卡片
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: _buildCreateCard(provider),
            ),
          ),
          const SliverToBoxAdapter(child: SizedBox(height: 24)),

          // 订阅列表标题
          SliverToBoxAdapter(
            child: Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: Text(
                '活跃订阅',
                style: TextStyle(
                  fontSize: 13,
                  fontWeight: FontWeight.w600,
                  color: const Color(0xFF8E8E93).withValues(alpha: 0.8),
                  letterSpacing: 0.5,
                ),
              ),
            ),
          ),
          const SliverToBoxAdapter(child: SizedBox(height: 8)),

          // 订阅列表
          if (provider.isLoading && provider.subscriptions.isEmpty)
            const SliverToBoxAdapter(
              child: Padding(
                padding: EdgeInsets.all(40),
                child: Center(child: CircularProgressIndicator(strokeWidth: 2)),
              ),
            )
          else if (provider.subscriptions.isEmpty)
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.all(40),
                child: Center(
                  child: Text(
                    '暂无订阅\n创建一个关键词订阅，系统会定时自动采集',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: 15,
                      color: const Color(0xFF8E8E93).withValues(alpha: 0.6),
                      height: 1.5,
                    ),
                  ),
                ),
              ),
            )
          else
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.symmetric(horizontal: 20),
                child: Container(
                  decoration: BoxDecoration(
                    color: const Color(0xFF1C1C1E),
                    borderRadius: BorderRadius.circular(13),
                  ),
                  child: Column(
                    children: [
                      for (var i = 0; i < provider.subscriptions.length; i++) ...[
                        if (i > 0)
                          const Divider(height: 0.33, indent: 16, color: Color(0xFF38383A)),
                        _SubscriptionTile(
                          subscription: provider.subscriptions[i],
                          onCancel: () {
                            provider.cancelSubscription(
                              provider.subscriptions[i].subscriptionId,
                            );
                          },
                        ),
                      ],
                    ],
                  ),
                ),
              ),
            ),

          const SliverToBoxAdapter(child: SizedBox(height: 40)),
        ],
      ),
    );
  }

  Widget _buildCreateCard(SubscriptionProvider provider) {
    return Container(
      decoration: BoxDecoration(
        color: const Color(0xFF1C1C1E),
        borderRadius: BorderRadius.circular(13),
      ),
      child: Column(
        children: [
          // 关键词输入
          Padding(
            padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
            child: TextField(
              controller: _keywordController,
              style: const TextStyle(fontSize: 17),
              decoration: InputDecoration(
                hintText: '输入订阅关键词',
                prefixIcon: Icon(
                  Icons.notifications_active_rounded,
                  color: const Color(0xFF8E8E93).withValues(alpha: 0.8),
                ),
              ),
              onChanged: (_) => setState(() {}),
            ),
          ),
          const Divider(height: 0.33, indent: 16, color: Color(0xFF38383A)),

          // 采集间隔
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            child: Row(
              children: [
                const Text('采集间隔', style: TextStyle(fontSize: 17)),
                const Spacer(),
                SegmentedButton<int>(
                  segments: const [
                    ButtonSegment(value: 1, label: Text('1h', style: TextStyle(fontSize: 13))),
                    ButtonSegment(value: 6, label: Text('6h', style: TextStyle(fontSize: 13))),
                    ButtonSegment(value: 12, label: Text('12h', style: TextStyle(fontSize: 13))),
                    ButtonSegment(value: 24, label: Text('24h', style: TextStyle(fontSize: 13))),
                  ],
                  selected: {_intervalHours},
                  onSelectionChanged: (v) => setState(() => _intervalHours = v.first),
                  style: ButtonStyle(
                    visualDensity: VisualDensity.compact,
                    tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    side: WidgetStateProperty.all(
                      const BorderSide(color: Color(0xFF48484A)),
                    ),
                  ),
                ),
              ],
            ),
          ),
          const Divider(height: 0.33, indent: 16, color: Color(0xFF38383A)),

          // 报警阈值
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10),
            child: Row(
              children: [
                const Text('报警阈值', style: TextStyle(fontSize: 17)),
                const SizedBox(width: 8),
                Text(
                  '情感 < $_alertThreshold 分时报警',
                  style: TextStyle(
                    fontSize: 13,
                    color: const Color(0xFF8E8E93).withValues(alpha: 0.6),
                  ),
                ),
                const Spacer(),
                SizedBox(
                  width: 60,
                  height: 36,
                  child: TextField(
                    keyboardType: TextInputType.number,
                    textAlign: TextAlign.center,
                    style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
                    decoration: InputDecoration(
                      contentPadding: const EdgeInsets.symmetric(horizontal: 8, vertical: 6),
                      filled: true,
                      fillColor: const Color(0xFF2C2C2E),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(8),
                        borderSide: BorderSide.none,
                      ),
                    ),
                    controller: TextEditingController(text: '$_alertThreshold'),
                    onChanged: (v) {
                      final n = int.tryParse(v);
                      if (n != null && n >= 0 && n <= 100) {
                        setState(() => _alertThreshold = n);
                      }
                    },
                  ),
                ),
              ],
            ),
          ),
          const Divider(height: 0.33, indent: 16, color: Color(0xFF38383A)),

          // 创建按钮
          Padding(
            padding: const EdgeInsets.all(16),
            child: SizedBox(
              width: double.infinity,
              height: 44,
              child: FilledButton(
                onPressed: provider.isLoading || _keywordController.text.trim().isEmpty
                    ? null
                    : _createSubscription,
                style: FilledButton.styleFrom(
                  backgroundColor: const Color(0xFF0A84FF),
                  disabledBackgroundColor: const Color(0xFF0A84FF).withValues(alpha: 0.3),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(10)),
                ),
                child: provider.isLoading
                    ? const SizedBox(
                        width: 20,
                        height: 20,
                        child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                      )
                    : const Text(
                        '创建订阅',
                        style: TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
                      ),
              ),
            ),
          ),
        ],
      ),
    );
  }
}

/// 单条订阅展示行
class _SubscriptionTile extends StatelessWidget {
  final dynamic subscription;
  final VoidCallback onCancel;

  const _SubscriptionTile({required this.subscription, required this.onCancel});

  @override
  Widget build(BuildContext context) {
    final isActive = subscription.status == 'active';

    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: Row(
        children: [
          // 状态指示灯
          Container(
            width: 8,
            height: 8,
            decoration: BoxDecoration(
              shape: BoxShape.circle,
              color: isActive ? const Color(0xFF30D158) : const Color(0xFF8E8E93),
            ),
          ),
          const SizedBox(width: 12),
          // 关键词和详情
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  subscription.keyword,
                  style: const TextStyle(fontSize: 17, fontWeight: FontWeight.w600),
                ),
                const SizedBox(height: 4),
                Text(
                  '每 ${subscription.intervalHours}h · 报警 < ${subscription.alertThreshold}分 · ${subscription.sources.join(", ")}',
                  style: TextStyle(
                    fontSize: 13,
                    color: const Color(0xFF8E8E93).withValues(alpha: 0.8),
                  ),
                ),
              ],
            ),
          ),
          // 取消按钮
          GestureDetector(
            onTap: () {
              showDialog(
                context: context,
                builder: (ctx) => AlertDialog(
                  backgroundColor: const Color(0xFF2C2C2E),
                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                  title: const Text('取消订阅'),
                  content: Text('确定取消对「${subscription.keyword}」的订阅吗？'),
                  actions: [
                    TextButton(
                      onPressed: () => Navigator.pop(ctx),
                      child: const Text('返回', style: TextStyle(color: Color(0xFF0A84FF))),
                    ),
                    TextButton(
                      onPressed: () {
                        Navigator.pop(ctx);
                        onCancel();
                      },
                      child: const Text('取消订阅', style: TextStyle(color: Color(0xFFFF453A))),
                    ),
                  ],
                ),
              );
            },
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              decoration: BoxDecoration(
                color: const Color(0xFFFF453A).withValues(alpha: 0.15),
                borderRadius: BorderRadius.circular(8),
              ),
              child: const Text(
                '取消',
                style: TextStyle(fontSize: 13, color: Color(0xFFFF453A), fontWeight: FontWeight.w600),
              ),
            ),
          ),
        ],
      ),
    );
  }
}
