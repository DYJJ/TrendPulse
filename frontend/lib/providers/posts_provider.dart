import 'package:flutter/foundation.dart';
import 'package:trendpulse/api/api_client.dart';
import 'package:trendpulse/models/post.dart';
import 'package:trendpulse/config.dart';

/// 帖子列表状态管理
///
/// 管理原始帖子的分页加载、筛选、排序、搜索状态。
class PostsProvider extends ChangeNotifier {
  final ApiClient _apiClient;

  List<Post> _posts = [];
  int _currentPage = 1;
  int _total = 0;
  bool _hasMore = true;
  bool _isLoading = false;
  String? _error;
  String? _taskId;

  // 筛选/排序/搜索状态字段
  String? _sourceFilter;
  String _sortBy = 'timestamp';
  String _sortOrder = 'desc';
  String? _searchQuery;

  PostsProvider(this._apiClient);

  // 只读访问器
  List<Post> get posts => _posts;
  int get currentPage => _currentPage;
  int get total => _total;
  bool get hasMore => _hasMore;
  bool get isLoading => _isLoading;
  String? get error => _error;
  String? get taskId => _taskId;

  // 筛选/排序/搜索访问器
  String? get sourceFilter => _sourceFilter;
  String get sortBy => _sortBy;
  String get sortOrder => _sortOrder;
  String? get searchQuery => _searchQuery;

  /// 加载指定任务的帖子列表（首页）
  Future<void> loadPosts(String taskId) async {
    _taskId = taskId;
    _currentPage = 1;
    _posts = [];
    _hasMore = true;
    _error = null;
    _isLoading = true;
    notifyListeners();

    try {
      final response = await _apiClient.getPosts(
        taskId,
        page: 1,
        pageSize: AppConfig.defaultPageSize,
        source: _sourceFilter,
        sortBy: _sortBy,
        sortOrder: _sortOrder,
        search: _searchQuery,
      );
      _posts = response.posts;
      _total = response.total;
      _hasMore = _posts.length < _total;
    } catch (e) {
      _error = e.toString();
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// 加载下一页
  Future<void> loadMore() async {
    if (_isLoading || !_hasMore || _taskId == null) return;

    _isLoading = true;
    _error = null;
    notifyListeners();

    try {
      _currentPage++;
      final response = await _apiClient.getPosts(
        _taskId!,
        page: _currentPage,
        pageSize: AppConfig.defaultPageSize,
        source: _sourceFilter,
        sortBy: _sortBy,
        sortOrder: _sortOrder,
        search: _searchQuery,
      );
      _posts.addAll(response.posts);
      _total = response.total;
      _hasMore = _posts.length < _total;
    } catch (e) {
      _error = e.toString();
      _currentPage--; // 回退页码
    } finally {
      _isLoading = false;
      notifyListeners();
    }
  }

  /// 设置平台筛选并重新加载
  Future<void> setSourceFilter(String? source) async {
    _sourceFilter = source;
    if (_taskId != null) {
      await loadPosts(_taskId!);
    }
  }

  /// 设置排序方式并重新加载
  Future<void> setSortBy(String field, {String order = 'desc'}) async {
    _sortBy = field;
    _sortOrder = order;
    if (_taskId != null) {
      await loadPosts(_taskId!);
    }
  }

  /// 设置搜索关键词并重新加载
  Future<void> setSearch(String? query) async {
    _searchQuery = (query != null && query.trim().isEmpty) ? null : query;
    if (_taskId != null) {
      await loadPosts(_taskId!);
    }
  }

  /// 刷新当前数据（保持筛选/排序/搜索条件不变）
  Future<void> refresh() async {
    if (_taskId != null) {
      await loadPosts(_taskId!);
    }
  }

  /// 清除状态
  void clear() {
    _posts = [];
    _currentPage = 1;
    _total = 0;
    _hasMore = true;
    _isLoading = false;
    _error = null;
    _taskId = null;
    _sourceFilter = null;
    _sortBy = 'timestamp';
    _sortOrder = 'desc';
    _searchQuery = null;
    notifyListeners();
  }
}
