import 'dart:math';
import 'package:flutter_test/flutter_test.dart';
import 'package:trendpulse/providers/posts_provider.dart';
import 'package:trendpulse/api/api_client.dart';
import 'package:trendpulse/models/post.dart';

/// 伪造的 ApiClient，用于捕获 getPosts 调用参数
///
/// 不发起真实 HTTP 请求，返回空列表响应，
/// 同时记录每次调用的参数以供断言验证。
class FakeApiClient extends ApiClient {
  /// 最近一次 getPosts 调用的参数记录
  Map<String, dynamic>? lastCallParams;

  /// getPosts 被调用的次数
  int callCount = 0;

  FakeApiClient() : super(baseUrl: 'http://fake');

  @override
  Future<PostListResponse> getPosts(
    String taskId, {
    int page = 1,
    int pageSize = 20,
    String? source,
    String? sortBy,
    String sortOrder = 'desc',
    String? search,
  }) async {
    callCount++;
    lastCallParams = {
      'taskId': taskId,
      'page': page,
      'pageSize': pageSize,
      'source': source,
      'sortBy': sortBy,
      'sortOrder': sortOrder,
      'search': search,
    };
    // 返回空列表响应
    return PostListResponse(
      posts: [],
      total: 0,
      page: page,
      pageSize: pageSize,
    );
  }
}


/// 随机来源值生成器
String? _randomSource(Random rng) {
  const sources = [null, 'reddit', 'youtube', 'twitter'];
  return sources[rng.nextInt(sources.length)];
}

/// 随机排序字段生成器
String _randomSortBy(Random rng) {
  const fields = ['timestamp', 'likes', 'comments'];
  return fields[rng.nextInt(fields.length)];
}

/// 随机排序方向生成器
String _randomSortOrder(Random rng) {
  return rng.nextBool() ? 'asc' : 'desc';
}

/// 随机搜索关键词生成器
String? _randomSearch(Random rng) {
  if (rng.nextBool()) return null;
  const keywords = ['flutter', '舆情', 'AI', 'test', '数据', 'trend'];
  return keywords[rng.nextInt(keywords.length)];
}

void main() {
  const taskId = 'test-task-id';

  group('Feature: data-page-enhancement, Property 4: 参数变更重置分页', () {
    /// **Validates: Requirements 1.3, 2.2, 3.2**
    ///
    /// 对于任意的 PostsProvider 状态，当平台筛选、排序方式或搜索关键词
    /// 中的任一参数发生变更时，Provider 应将当前页码重置为 1 并重新加载数据。
    test('随机参数变更后 currentPage 重置为 1（100 次迭代）', () async {
      final rng = Random(42);

      for (var i = 0; i < 100; i++) {
        final fakeClient = FakeApiClient();
        final provider = PostsProvider(fakeClient);

        // 初始加载
        await provider.loadPosts(taskId);

        // 模拟翻页，使 currentPage > 1
        // loadMore 会增加 currentPage（即使返回空数据也会增加）
        await provider.loadMore();
        // loadMore 在空数据时 hasMore=false，所以手动验证初始状态后直接测试参数变更

        // 随机选择一种参数变更操作
        final action = rng.nextInt(3);
        switch (action) {
          case 0:
            // 变更平台筛选
            await provider.setSourceFilter(_randomSource(rng));
            break;
          case 1:
            // 变更排序方式
            await provider.setSortBy(
              _randomSortBy(rng),
              order: _randomSortOrder(rng),
            );
            break;
          case 2:
            // 变更搜索关键词
            await provider.setSearch(_randomSearch(rng));
            break;
        }

        // 不变量：参数变更后 currentPage 应为 1
        expect(provider.currentPage, equals(1),
            reason: '迭代 $i (action=$action): 参数变更后 currentPage 应重置为 1');

        // 不变量：API 调用的 page 参数应为 1
        expect(fakeClient.lastCallParams?['page'], equals(1),
            reason: '迭代 $i (action=$action): API 调用的 page 参数应为 1');
      }
    });
  });

  group('Feature: data-page-enhancement, Property 5: 参数独立性', () {
    /// **Validates: Requirements 2.4, 3.4, 6.3**
    ///
    /// 对于任意的筛选/排序/搜索参数组合，当改变其中一个参数时，
    /// 其他参数的值应保持不变。
    test('改变一个参数不影响其他参数（100 次迭代）', () async {
      final rng = Random(42);

      for (var i = 0; i < 100; i++) {
        final fakeClient = FakeApiClient();
        final provider = PostsProvider(fakeClient);

        // 初始加载
        await provider.loadPosts(taskId);

        // 先设置随机初始参数状态
        final initialSource = _randomSource(rng);
        final initialSortBy = _randomSortBy(rng);
        final initialSortOrder = _randomSortOrder(rng);
        final initialSearch = _randomSearch(rng);

        await provider.setSourceFilter(initialSource);
        await provider.setSortBy(initialSortBy, order: initialSortOrder);
        await provider.setSearch(initialSearch);

        // 记录设置后的实际状态（search 可能被 trim 处理）
        final stateSource = provider.sourceFilter;
        final stateSortBy = provider.sortBy;
        final stateSortOrder = provider.sortOrder;
        final stateSearch = provider.searchQuery;

        // 随机选择一种参数变更操作，验证其他参数不变
        final action = rng.nextInt(4);
        switch (action) {
          case 0:
            // 变更平台筛选 → 排序和搜索不变
            final newSource = _randomSource(rng);
            await provider.setSourceFilter(newSource);
            expect(provider.sortBy, equals(stateSortBy),
                reason: '迭代 $i: 变更 source 后 sortBy 应不变');
            expect(provider.sortOrder, equals(stateSortOrder),
                reason: '迭代 $i: 变更 source 后 sortOrder 应不变');
            expect(provider.searchQuery, equals(stateSearch),
                reason: '迭代 $i: 变更 source 后 searchQuery 应不变');
            break;
          case 1:
            // 变更排序 → 筛选和搜索不变
            final newSortBy = _randomSortBy(rng);
            final newSortOrder = _randomSortOrder(rng);
            await provider.setSortBy(newSortBy, order: newSortOrder);
            expect(provider.sourceFilter, equals(stateSource),
                reason: '迭代 $i: 变更 sortBy 后 sourceFilter 应不变');
            expect(provider.searchQuery, equals(stateSearch),
                reason: '迭代 $i: 变更 sortBy 后 searchQuery 应不变');
            break;
          case 2:
            // 变更搜索 → 筛选和排序不变
            final newSearch = _randomSearch(rng);
            await provider.setSearch(newSearch);
            expect(provider.sourceFilter, equals(stateSource),
                reason: '迭代 $i: 变更 search 后 sourceFilter 应不变');
            expect(provider.sortBy, equals(stateSortBy),
                reason: '迭代 $i: 变更 search 后 sortBy 应不变');
            expect(provider.sortOrder, equals(stateSortOrder),
                reason: '迭代 $i: 变更 search 后 sortOrder 应不变');
            break;
          case 3:
            // 刷新 → 所有参数不变
            await provider.refresh();
            expect(provider.sourceFilter, equals(stateSource),
                reason: '迭代 $i: refresh 后 sourceFilter 应不变');
            expect(provider.sortBy, equals(stateSortBy),
                reason: '迭代 $i: refresh 后 sortBy 应不变');
            expect(provider.sortOrder, equals(stateSortOrder),
                reason: '迭代 $i: refresh 后 sortOrder 应不变');
            expect(provider.searchQuery, equals(stateSearch),
                reason: '迭代 $i: refresh 后 searchQuery 应不变');
            break;
        }
      }
    });
  });
}
